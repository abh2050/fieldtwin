"""Replay each Gate 4 field scenario through the Gate 5 streaming engine and collect alarm starts.

This is what an operator's system would see: telemetry and quality flags, in time order. Fault truth
and scenario declarations are not read here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from packages.anomaly_detection.contracts import InferenceRequest, SensorObservation, SensorQuality
from packages.anomaly_detection.inference import StreamingEngine, load_bundle
from packages.decision_engine.rules import Alarm, EvidenceSensor
from packages.scenario_engine.field_simulation import simulate_by_id
from pipelines.acquire.common import core

FIELD_ASSET = "AETHER-FIELD"
SCENARIOS = (
    "AETHER-NET-NORMAL",
    "AETHER-FAULT-001-NET",
    "AETHER-NET-COMPRESSOR-DERATE",
    "AETHER-NET-SENSOR-DRIFT",
    "AETHER-NET-COMM-DROPOUT",
    "AETHER-NET-PLANNED-SHUTDOWN",
)


def load_rules(root: Path) -> dict[str, Any]:
    return core.load_yaml(root / "config" / "decision" / "gate7_rules.yaml")


def model_checksum(root: Path, rules: dict[str, Any]) -> str:
    results = json.loads((root / rules["detector"]["results_file"]).read_text())
    return results["artifacts"]["hist_gradient_boosting"]["sha256"]


def scenario_alarms(
    scenario_id: str, root: Path, rules: dict[str, Any]
) -> tuple[list[Alarm], dict[str, Any]]:
    expected = model_checksum(root, rules)
    bundle = load_bundle(root / rules["detector"]["model_file"], expected)
    run = simulate_by_id(scenario_id)
    telemetry = run.telemetry
    sensors = set(bundle.spec.sensors)
    telemetry = telemetry[telemetry["tag"].isin(sensors)]
    asset_of = dict(zip(telemetry["tag"], telemetry["asset_id"], strict=False))
    degraded_values = set(rules["data_quality"]["degraded_qualities"])
    engine = StreamingEngine(bundle)
    lookback = timedelta(hours=rules["evidence"]["lookback_h"])

    alarms: list[Alarm] = []
    starts: list[datetime] = []
    bad_by_time: dict[datetime, set[str]] = {}
    windows = 0
    for moment, rows in telemetry.groupby("simulated_time", sort=True):
        at = pd.Timestamp(moment).to_pydatetime()
        at = at if at.tzinfo else at.replace(tzinfo=UTC)
        observations = []
        bad: set[str] = set()
        for row in rows.itertuples(index=False):
            quality = SensorQuality(row.quality)
            good = quality is SensorQuality.GOOD and row.value == row.value
            if quality.value in degraded_values:
                bad.add(row.tag)
            observations.append(
                SensorObservation(
                    tag=row.tag,
                    timestamp=at,
                    value=float(row.value) if good else None,
                    quality=quality,
                )
            )
        bad_by_time[at] = bad
        predictions = engine.ingest(
            InferenceRequest(
                asset_id=FIELD_ASSET,
                domain=bundle.domain,
                measurement_definitions={},
                observations=observations,
                model_id=bundle.model_id,
                model_version=bundle.model_version,
            )
        )
        for prediction in predictions:
            windows += 1
            if not prediction.alarm_started:
                continue
            window_start = at - timedelta(
                seconds=bundle.spec.sample_s * (bundle.spec.window_samples - 1)
            )
            window_bad = set().union(
                *(tags for t, tags in bad_by_time.items() if window_start <= t <= at)
            )
            evidence = [
                EvidenceSensor(
                    tag=ref.tag,
                    asset_id=asset_of[ref.tag],
                    deviation=ref.deviation,
                    degraded_quality=ref.tag in window_bad,
                )
                for ref in prediction.evidence[: rules["detector"]["evidence_sensors"]]
            ]
            earlier = [s for s in starts if at - s <= lookback]
            digest = hashlib.sha256(
                f"{run.run_id}|{prediction.prediction_id}".encode()
            ).hexdigest()[:16]
            alarms.append(
                Alarm(
                    alarm_id=f"ALM-{digest}",
                    scenario_id=scenario_id,
                    scenario_run_id=run.run_id,
                    started_at=at,
                    score=float(prediction.score or 0.0),
                    threshold=prediction.decision_threshold,
                    model_id=bundle.model_id,
                    model_version=bundle.model_version,
                    model_sha256=expected,
                    evidence=evidence,
                    earlier_starts_in_lookback=len(earlier),
                    first_alarm_at=starts[0] if starts else at,
                )
            )
            starts.append(at)
    epoch = pd.Timestamp(telemetry["simulated_time"].min()).to_pydatetime()
    meta = {
        "scenario_id": scenario_id,
        "scenario_run_id": run.run_id,
        "epoch": epoch if epoch.tzinfo else epoch.replace(tzinfo=UTC),
        "windows": windows,
        "output_sha256": run.canonical_sha256(),
    }
    return alarms, meta
