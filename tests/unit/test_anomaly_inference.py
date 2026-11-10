"""Streaming contracts: same answers as batch, no route for fault truth, and no crossed domains."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from pydantic import ValidationError

from packages.anomaly_detection.contracts import (
    InferenceRequest,
    InputDomain,
    QualityStatus,
    SensorObservation,
    SensorQuality,
)
from packages.anomaly_detection.detectors import make_detector
from packages.anomaly_detection.evaluation import AlarmRule, episode_starts
from packages.anomaly_detection.features import FeatureSpec, build_features
from packages.anomaly_detection.inference import (
    ContractViolation,
    ModelBundle,
    StreamingEngine,
    load_bundle,
    save_bundle,
)
from tests.conftest import REPO_ROOT

SPEC = FeatureSpec(("s0", "s1", "s2"), 10, 5, 1)
RULE = AlarmRule(2, 60, 5)
DEFINITIONS = {s: f"def.{s}" for s in SPEC.sensors}
START = datetime(2040, 1, 1, tzinfo=UTC)
METHODS = [
    "static_threshold",
    "rolling_deviation",
    "logistic_regression",
    "isolation_forest",
    "hist_gradient_boosting",
]


def _series(seed=0, n=400):
    rng = np.random.default_rng(seed)
    values = rng.normal(size=(n, 3))
    values[n // 2 :, 1] += 6.0
    values[50:60, 2] = np.nan
    return values, int(START.timestamp()) + np.arange(n)


def _bundle(method: str) -> tuple[ModelBundle, np.ndarray, np.ndarray, np.ndarray]:
    values, times = _series()
    features, ends = build_features(values, times, SPEC)
    y = (ends >= 200).astype(int)
    seq = np.zeros(len(y), dtype=int)
    detector = make_detector(method, SPEC.names, seed=1, baseline_windows=8, gap_windows=2).fit(
        features, y, seq
    )
    threshold = float(np.nanquantile(detector.score(features, seq), 0.8))
    bundle = ModelBundle(
        "m",
        "1",
        InputDomain.AETHER_SYNTHETIC,
        detector,
        SPEC,
        threshold,
        RULE,
        {0: "NORMAL", 1: "FAULT"},
        DEFINITIONS,
        np.zeros(3),
        np.ones(3),
    )
    return bundle, values, times, features


def _request(values, moment, *, quality=SensorQuality.GOOD, **overrides):
    observations = [
        SensorObservation(
            tag=tag,
            timestamp=moment,
            value=None if np.isnan(v) else float(v),
            quality=SensorQuality.BAD_COMM_LOST if np.isnan(v) else quality,
        )
        for tag, v in zip(SPEC.sensors, values, strict=True)
    ]
    fields = {
        "asset_id": "FIELD",
        "domain": InputDomain.AETHER_SYNTHETIC,
        "measurement_definitions": DEFINITIONS,
        "observations": observations,
        "model_id": "m",
        "model_version": "1",
    }
    return InferenceRequest(**(fields | overrides))


def _stream(engine, values, times):
    output = []
    for row, epoch in zip(values, times, strict=True):
        output += engine.ingest(_request(row, datetime.fromtimestamp(int(epoch), tz=UTC)))
    return output


@pytest.mark.parametrize("method", METHODS)
def test_streaming_matches_batch_scores_and_alarms(method):
    bundle, values, times, features = _bundle(method)
    predictions = _stream(StreamingEngine(bundle), values, times)
    batch = bundle.detector.score(features, np.zeros(len(features), dtype=int))
    streamed = np.array([np.nan if p.score is None else p.score for p in predictions])
    assert len(streamed) == len(batch)
    assert np.allclose(streamed, batch, equal_nan=True, rtol=1e-5, atol=1e-6)
    starts, _ = episode_starts(batch, np.arange(len(batch)) * 5, bundle.threshold, RULE)
    assert [i for i, p in enumerate(predictions) if p.alarm_started] == starts.tolist()


def test_prediction_carries_every_declared_field():
    bundle, values, times, _ = _bundle("hist_gradient_boosting")
    predictions = _stream(StreamingEngine(bundle), values, times)
    alarm = next(p for p in predictions if p.alarm_started)
    assert alarm.prediction_id and alarm.asset_id == "FIELD"
    assert (
        alarm.detection_timestamp is not None and alarm.event_timestamp <= alarm.detection_timestamp
    )
    assert alarm.decision_threshold == bundle.threshold and alarm.score is not None
    assert alarm.provenance_class == "INFERRED" and alarm.input_provenance == "SYNTHETIC"
    assert alarm.model_id == "m" and alarm.model_version == "1"
    assert alarm.predicted_class in ("FAULT", "ANOMALY_UNCLASSIFIED") and alarm.evidence
    assert alarm.evidence[0].window_start < alarm.evidence[0].window_end
    assert alarm.evidence[0].measurement_definition_id.startswith("def.")
    assert len({p.prediction_id for p in predictions}) == len(predictions)


def test_lost_readings_mark_quality_as_degraded():
    bundle, values, times, _ = _bundle("static_threshold")
    predictions = _stream(StreamingEngine(bundle), values[:100], times[:100])
    assert {
        p.quality_status
        for p in predictions
        if 55 <= (p.event_timestamp - START).total_seconds() <= 65
    } == {QualityStatus.DEGRADED}
    assert predictions[0].quality_status is QualityStatus.OK


def test_warm_up_is_reported_as_insufficient_data():
    bundle, values, times, _ = _bundle("rolling_deviation")
    assert (
        _stream(StreamingEngine(bundle), values[:30], times[:30])[0].quality_status
        is QualityStatus.INSUFFICIENT_DATA
    )


@pytest.mark.parametrize(
    "tag",
    ["truth_severity_GS-A", "TRUTH_fault", "diag_newton", "class", "label", "severity", "onset_s"],
)
def test_truth_cannot_arrive_as_a_sensor(tag):
    with pytest.raises(ValidationError):
        SensorObservation(tag=tag, timestamp=START, value=1.0, quality=SensorQuality.GOOD)


@pytest.mark.parametrize("field", ["severity", "fault_onset_s", "truth", "label"])
def test_contracts_refuse_undeclared_fields(field):
    with pytest.raises(ValidationError):
        SensorObservation(
            tag="s0", timestamp=START, value=1.0, quality=SensorQuality.GOOD, **{field: 1}
        )
    with pytest.raises(ValidationError):
        InferenceRequest(
            asset_id="A",
            domain=InputDomain.AETHER_SYNTHETIC,
            measurement_definitions={},
            observations=[],
            model_id="m",
            model_version="1",
            **{field: 1},
        )


def test_a_model_refuses_another_domain():
    bundle, values, _, _ = _bundle("static_threshold")
    with pytest.raises(ContractViolation):
        StreamingEngine(bundle).ingest(
            _request(values[0], START, domain=InputDomain.OFFSHORE_BENCHMARK)
        )


def test_a_model_refuses_a_different_model_or_definition():
    bundle, values, _, _ = _bundle("static_threshold")
    engine = StreamingEngine(bundle)
    with pytest.raises(ContractViolation):
        engine.ingest(_request(values[0], START, model_version="2"))
    with pytest.raises(ContractViolation):
        engine.ingest(
            _request(values[0], START, measurement_definitions={"s0": "other.definition"})
        )
    with pytest.raises(ContractViolation):
        engine.ingest(_request(values[0], START, measurement_definitions={"unknown": "x"}))


def test_a_model_refuses_unknown_tags_and_time_going_backward():
    bundle, values, _, _ = _bundle("static_threshold")
    engine = StreamingEngine(bundle)
    unknown = SensorObservation(tag="other", timestamp=START, value=1.0, quality=SensorQuality.GOOD)
    with pytest.raises(ContractViolation):
        engine.ingest(_request(values[0], START, observations=[unknown]))
    engine.ingest(_request(values[0], START))
    with pytest.raises(ContractViolation):
        engine.ingest(_request(values[0], START - timedelta(seconds=1)))


def test_assets_keep_separate_state():
    bundle, values, times, _ = _bundle("static_threshold")
    engine = StreamingEngine(bundle)
    for row, epoch in zip(values[:15], times[:15], strict=True):
        engine.ingest(_request(row, datetime.fromtimestamp(int(epoch), tz=UTC)))
    assert engine.ingest(_request(values[0], START, asset_id="OTHER")) == []
    assert len(engine.assets) == 2


def test_artifact_checksum_is_enforced(tmp_path):
    bundle, *_ = _bundle("static_threshold")
    path = tmp_path / "model.joblib"
    checksum = save_bundle(bundle, path)
    assert load_bundle(path, checksum).threshold == bundle.threshold
    with pytest.raises(ContractViolation):
        load_bundle(path, "0" * 64)


def test_inference_code_cannot_import_simulator_truth_or_labels():
    for name in ("inference", "contracts", "features", "detectors"):
        tree = ast.parse((REPO_ROOT / f"packages/anomaly_detection/{name}.py").read_text())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
            elif isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
        assert not [
            m
            for m in imported
            if "scenario_engine" in m or m.endswith("labels") or "pipelines" in m
        ], name


def test_prediction_contract_has_no_truth_field():
    from packages.anomaly_detection.contracts import Prediction

    for field in Prediction.model_fields:
        assert not any(word in field for word in ("severity", "onset", "truth"))
