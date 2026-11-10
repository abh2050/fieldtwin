"""CPU latency and memory of the streaming path, in one fresh single-thread process per model."""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
import tracemalloc
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from packages.anomaly_detection.contracts import InferenceRequest, SensorObservation, SensorQuality
from packages.anomaly_detection.features import build_features
from packages.anomaly_detection.inference import StreamingEngine, load_bundle
from pipelines.experiments.common import MODELS, hardware, read_result, write_result

REPLAY_SAMPLES_3W = 9000
AGREEMENT_RTOL, AGREEMENT_ATOL = 1e-4, 1e-5


def _replay_series(bundle) -> tuple[np.ndarray, np.ndarray, str]:
    if bundle.domain.value == "OFFSHORE_BENCHMARK":
        from pipelines.experiments.three_w_audit import batch_root
        from pipelines.experiments.three_w_data import read_instance

        fold = read_result("3w_holdout")["fold"]
        audits = pd.read_parquet(MODELS.parent / "3w_label_audit.parquet")
        chosen = (
            audits[audits["source_well_id"].isin(fold["test_wells"]) & (audits["filed_class"] == 0)]
            .sort_values("source_instance_id")
            .iloc[0]
        )
        path = next(batch_root().glob(f"dataset/*/{chosen['source_instance_id']}.parquet"))
        values, times, _ = read_instance(path, bundle.spec.sensors)
        return values[:REPLAY_SAMPLES_3W], times[:REPLAY_SAMPLES_3W], chosen["source_instance_id"]
    from pipelines.experiments.aether_data import EPOCH_S, TELEMETRY

    frame = pd.read_parquet(TELEMETRY / "test-RESTRICTION-00.parquet")
    return (
        frame[list(bundle.spec.sensors)].to_numpy(dtype=float),
        frame["offset_s"].to_numpy(dtype=np.int64) + EPOCH_S,
        "test-RESTRICTION-00",
    )


def _requests(bundle, values, times, asset):
    sensors = bundle.spec.sensors
    aether = bundle.domain.value == "AETHER_SYNTHETIC"
    for row, epoch in zip(values, times, strict=True):
        moment = datetime.fromtimestamp(int(epoch), tz=UTC)
        observations = []
        for tag, value in zip(sensors, row, strict=True):
            if value == value:
                observations.append(
                    SensorObservation(
                        tag=tag, timestamp=moment, value=float(value), quality=SensorQuality.GOOD
                    )
                )
            elif aether:
                observations.append(
                    SensorObservation(
                        tag=tag, timestamp=moment, value=None, quality=SensorQuality.BAD_COMM_LOST
                    )
                )
        yield InferenceRequest(
            asset_id=asset,
            domain=bundle.domain,
            measurement_definitions={},
            observations=observations,
            model_id=bundle.model_id,
            model_version=bundle.model_version,
        )


def worker(path: str, expected_sha256: str) -> None:
    started = time.perf_counter()
    bundle = load_bundle(MODELS / path, expected_sha256)
    load_seconds = time.perf_counter() - started
    values, times, source = _replay_series(bundle)
    requests = list(_requests(bundle, values, times, "REPLAY"))
    engine = StreamingEngine(bundle)
    boundary, other, scores = [], [], []
    for request in requests:
        begun = time.perf_counter_ns()
        predictions = engine.ingest(request)
        elapsed = time.perf_counter_ns() - begun
        if predictions:
            boundary.append(elapsed)
            scores.append(np.nan if predictions[-1].score is None else predictions[-1].score)
        else:
            other.append(elapsed)
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        1024 * 1024 if sys.platform == "darwin" else 1024
    )
    tracemalloc.start()
    measured = StreamingEngine(bundle)
    for request in requests[: min(len(requests), 3000)]:
        measured.ingest(request)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    features, _ = build_features(values, times, bundle.spec)
    batch = bundle.detector.score(features, np.zeros(len(features), dtype=np.int64))
    streamed = np.array(scores)
    agree = len(batch) == len(streamed) and bool(
        np.allclose(streamed, batch, rtol=AGREEMENT_RTOL, atol=AGREEMENT_ATOL, equal_nan=True)
    )
    boundary_ms = np.array(boundary) / 1e6
    print(
        json.dumps(
            {
                "model": bundle.model_id,
                "replay_source": source,
                "samples": len(requests),
                "windows": len(boundary),
                "window_latency_ms": {
                    "p50": float(np.quantile(boundary_ms, 0.5)),
                    "p95": float(np.quantile(boundary_ms, 0.95)),
                    "p99": float(np.quantile(boundary_ms, 0.99)),
                    "max": float(boundary_ms.max()),
                },
                "non_window_sample_latency_ms_p50": float(np.quantile(np.array(other) / 1e6, 0.5))
                if other
                else None,
                "load_seconds": load_seconds,
                "peak_python_allocation_mb": peak / 2**20,
                "process_peak_rss_mb": rss_mb,
                "batch_stream_agree": agree,
                "windows_compared": min(len(batch), len(streamed)),
            }
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--sha")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.sha)
        return 0
    artifacts = {
        **read_result("3w_holdout")["artifacts"],
        **{f"aether:{k}": v for k, v in read_result("aether_held_out")["artifacts"].items()},
    }
    rows = []
    environment = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PYTHONWARNINGS": "ignore",
    }
    for key, item in artifacts.items():
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pipelines.experiments.inference_perf",
                "--worker",
                item["path"],
                "--sha",
                item["sha256"],
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=True,
        )
        row = json.loads(done.stdout.strip().splitlines()[-1]) | {
            "artifact_bytes": item["bytes"],
            "artifact_sha256": item["sha256"],
        }
        rows.append(row)
        print(key, row["window_latency_ms"]["p95"], row["batch_stream_agree"], flush=True)
    write_result("inference_performance", {"rows": rows, "threads": 1, "hardware": hardware()})
    return 0 if all(r["batch_stream_agree"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
