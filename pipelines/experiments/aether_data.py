"""Generate the AETHER benchmark under the process guard. Telemetry and fault truth are stored apart."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from packages.anomaly_detection.evaluation import AlarmRule
from packages.anomaly_detection.features import FeatureSpec, build_features
from packages.scenario_engine.benchmark_runs import (
    all_cases,
    fault_onset_s,
    sensor_tags,
    simulate_case,
)
from packages.scenario_engine.execution import run_with_timeout
from pipelines.experiments.common import EXPERIMENTS, Track, write_result
from pipelines.experiments.three_w_audit import evaluation_config

ROOT = EXPERIMENTS / "aether"
TELEMETRY = ROOT / "telemetry"
TRUTH = ROOT / "truth"
CASE_TIMEOUT_S = 180.0
EPOCH_S = 2208988800  # 2040-01-01T00:00:00Z, the simulated clock.


def simulate_to_files(index: int) -> dict:
    """Runs in a child process."""
    case = all_cases()[index]
    run = simulate_case(case)
    run.telemetry.to_parquet(TELEMETRY / f"{case.case_id}.parquet", index=False)
    run.labels.to_parquet(TRUTH / f"{case.case_id}.parquet", index=False)
    digest = hashlib.sha256(
        pd.util.hash_pandas_object(run.telemetry.round(6), index=False).values.tobytes()
    ).hexdigest()
    return {"telemetry_sha256": digest, "parameter_sha256": case.parameter_sha256()}


def generate(workers: int = 8) -> dict:
    TELEMETRY.mkdir(parents=True, exist_ok=True)
    TRUTH.mkdir(parents=True, exist_ok=True)
    cases = all_cases()
    log_path = ROOT / "generation_log.jsonl"
    with open(log_path, "w") as log, ThreadPoolExecutor(workers) as pool:
        reports = list(
            pool.map(
                lambda item: run_with_timeout(
                    "pipelines.experiments.aether_data:simulate_to_files",
                    {"index": item[0]},
                    timeout_s=CASE_TIMEOUT_S,
                    label=item[1].case_id,
                    log=log,
                ),
                enumerate(cases),
            )
        )
    outcomes: dict[str, int] = {}
    for report in reports:
        outcomes[report.outcome.value] = outcomes.get(report.outcome.value, 0) + 1
    done = [r.result for r in reports if r.result is not None]
    manifest = {
        "cases": len(cases),
        "outcomes": outcomes,
        "failed": [
            {"case": r.label, "outcome": r.outcome.value, "detail": (r.detail or "")[:300]}
            for r in reports
            if not r.result
        ],
        "dataset_sha256": hashlib.sha256(
            "".join(sorted(r["telemetry_sha256"] for r in done)).encode()
        ).hexdigest(),
        "parameter_sets_sha256": hashlib.sha256(
            "".join(sorted(r["parameter_sha256"] for r in done)).encode()
        ).hexdigest(),
        "max_case_seconds": round(max(r.elapsed_s for r in reports), 3),
        "median_case_seconds": round(float(np.median([r.elapsed_s for r in reports])), 3),
        "split_counts": pd.Series([c.split for c in cases]).value_counts().to_dict(),
        "regime_counts": pd.Series([c.regime for c in cases]).value_counts().to_dict(),
        "category_counts": pd.Series([c.category for c in cases]).value_counts().to_dict(),
        "provenance": "SYNTHETIC",
    }
    write_result("aether_dataset", manifest)
    return manifest


def spec_for() -> FeatureSpec:
    settings = evaluation_config()["aether"]
    return FeatureSpec(tuple(sensor_tags()), settings["window_samples"], 300, 300)


def rule_for() -> AlarmRule:
    settings = evaluation_config()["aether"]
    return AlarmRule(settings["persistence_windows"], settings["suppression_s"], 300)


def features_of(telemetry: pd.DataFrame, spec: FeatureSpec) -> tuple[np.ndarray, np.ndarray]:
    """Only sensor values go in. `telemetry` has no truth column by construction."""
    values = telemetry[list(spec.sensors)].to_numpy(dtype=float)
    offsets = telemetry["offset_s"].to_numpy(dtype=np.int64)
    features, ends = build_features(values, offsets + EPOCH_S, spec)
    return features, offsets[ends]


def load_track() -> tuple[Track, FeatureSpec]:
    spec = spec_for()
    parts, tables = [], []
    for case in all_cases():
        path = TELEMETRY / f"{case.case_id}.parquet"
        if not path.exists():
            continue  # A refused case is listed in the dataset manifest.
        features, offsets = features_of(pd.read_parquet(path), spec)
        truth = (
            pd.read_parquet(TRUTH / f"{case.case_id}.parquet").set_index("offset_s").loc[offsets]
        )
        parts.append(features)
        tables.append(
            pd.DataFrame(
                {
                    "seq": case.case_id,
                    "cluster": case.case_id,
                    "t": offsets,
                    "y": truth["y"].to_numpy(dtype=np.int16),
                    "planned_active": truth["planned_active"].to_numpy(),
                    "dropout_active": truth["dropout_active"].to_numpy(),
                    "split": case.split,
                    "regime": case.regime,
                    "category": case.category,
                    "onset_s": fault_onset_s(case) if fault_onset_s(case) is not None else -1,
                }
            )
        )
    return Track(np.concatenate(parts), spec.names, pd.concat(tables, ignore_index=True)), spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    print(json.dumps(generate(parser.parse_args().workers), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
