"""Streaming inference. It sees only what a request carries, so fault truth can't reach it."""

from __future__ import annotations

import hashlib
import io
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import joblib
import numpy as np

from .contracts import (
    EvidenceReference,
    InferenceRequest,
    InputDomain,
    Prediction,
    QualityStatus,
    SensorObservation,
    SensorQuality,
)
from .detectors import Detector
from .evaluation import AlarmRule, AlarmState
from .features import FeatureSpec, window_stats

_INPUT_PROVENANCE = {InputDomain.OFFSHORE_BENCHMARK: "OBSERVED", InputDomain.AETHER_SYNTHETIC: "SYNTHETIC"}
_TOP_EVIDENCE = 3


class ContractViolation(ValueError):
    """A request doesn't match the model it asks for."""


@dataclass(frozen=True)
class ModelBundle:
    model_id: str
    model_version: str
    domain: InputDomain
    detector: Detector
    spec: FeatureSpec
    threshold: float
    rule: AlarmRule
    class_names: dict[int, str]
    measurement_definitions: dict[str, str]
    normal_median: np.ndarray
    normal_scale: np.ndarray


def save_bundle(bundle: ModelBundle, path) -> str:
    """Write the bundle and return its SHA-256."""
    buffer = io.BytesIO()
    joblib.dump(bundle, buffer, compress=3)
    payload = buffer.getvalue()
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def load_bundle(path, expected_sha256: str | None = None) -> ModelBundle:
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise ContractViolation(f"artifact checksum {actual} is not the expected {expected_sha256}")
    return joblib.load(io.BytesIO(payload))


@dataclass
class _AssetState:
    alarm: AlarmState
    samples: deque
    quality_bad: deque
    history: deque
    samples_seen: int = 0
    last_time: int | None = None
    episode_event_time: int | None = None
    alarm_started_at: int | None = None
    extra: dict = field(default_factory=dict)


class StreamingEngine:
    def __init__(self, bundle: ModelBundle):
        self.bundle = bundle
        self.columns = {tag: i for i, tag in enumerate(bundle.spec.sensors)}
        self.assets: dict[str, _AssetState] = {}

    def _state(self, asset: str) -> _AssetState:
        if asset not in self.assets:
            spec = self.bundle.spec
            self.assets[asset] = _AssetState(
                AlarmState(self.bundle.rule),
                deque(maxlen=spec.window_samples),
                deque(maxlen=spec.window_samples),
                deque(maxlen=self.bundle.detector.history_windows),
            )
        return self.assets[asset]

    def _validate(self, request: InferenceRequest) -> None:
        bundle = self.bundle
        if request.model_id != bundle.model_id or request.model_version != bundle.model_version:
            raise ContractViolation("request names a different model")
        if request.domain is not bundle.domain:
            raise ContractViolation(f"a {bundle.domain} model can't score {request.domain} data")
        for tag, definition in request.measurement_definitions.items():
            expected = bundle.measurement_definitions.get(tag)
            if expected is None:
                raise ContractViolation(f"{tag} isn't an input of this model")
            if expected != definition:
                raise ContractViolation(f"{tag} is {definition}, and this model needs {expected}")

    def ingest(self, request: InferenceRequest) -> list[Prediction]:
        """Process observations in time order. Predictions come out only at window boundaries."""
        self._validate(request)
        grouped: dict[datetime, list[SensorObservation]] = {}
        for observation in request.observations:
            if observation.tag not in self.columns:
                raise ContractViolation(f"{observation.tag} isn't an input of this model")
            grouped.setdefault(observation.timestamp, []).append(observation)
        predictions = []
        for moment in sorted(grouped):
            made = self._sample(request.asset_id, request.domain, moment, grouped[moment])
            if made is not None:
                predictions.append(made)
        return predictions

    def _sample(self, asset: str, domain: InputDomain, moment: datetime, rows: list[SensorObservation]) -> Prediction | None:
        spec = self.bundle.spec
        state = self._state(asset)
        epoch = int(moment.timestamp())
        if state.last_time is not None and epoch <= state.last_time:
            raise ContractViolation(f"observation at {moment} is not after the previous one")
        state.last_time = epoch
        values = np.full(len(spec.sensors), np.nan)
        bad = False
        for row in rows:
            if row.quality is SensorQuality.GOOD and row.value is not None:
                values[self.columns[row.tag]] = row.value
            elif row.quality is not SensorQuality.GOOD:
                bad = True
        state.samples.append(values)
        state.quality_bad.append(bad)
        state.samples_seen += 1
        if epoch % spec.stride_s != 0 or len(state.samples) < spec.window_samples:
            return None
        return self._window(asset, domain, moment, epoch, state)

    def _window(self, asset: str, domain: InputDomain, moment: datetime, epoch: int, state: _AssetState) -> Prediction:
        bundle = self.bundle
        spec = bundle.spec
        window = np.stack(state.samples)[None, :, :]
        row = window_stats(window, spec.sample_s)
        state.history.append(row[0])
        features = np.stack(state.history)
        score = float(bundle.detector.score(features, np.zeros(len(features), dtype=np.int64))[-1])
        known = score == score
        started = state.alarm.step(score, bundle.threshold, epoch)
        flag = known and score >= bundle.threshold
        if started:
            state.alarm_started_at = epoch
            state.episode_event_time = state.alarm.first_above_of_run
        label = "NORMAL"
        if flag or state.alarm.active:
            label = "ANOMALY"
            predicted = bundle.detector.predict_class(row)
            if predicted is not None:
                label = bundle.class_names.get(int(predicted[0]), "ANOMALY")
                label = "ANOMALY_UNCLASSIFIED" if label == "NORMAL" else label
        status = QualityStatus.OK
        if not known:
            status = QualityStatus.INSUFFICIENT_DATA
        elif any(state.quality_bad):
            status = QualityStatus.DEGRADED
        event_time = moment
        if started and state.episode_event_time is not None:
            event_time = datetime.fromtimestamp(state.episode_event_time, tz=moment.tzinfo or UTC)
        return Prediction(
            prediction_id=hashlib.sha256(f"{bundle.model_id}|{bundle.model_version}|{asset}|{epoch}".encode()).hexdigest()[:32],
            asset_id=asset,
            event_timestamp=event_time,
            detection_timestamp=moment if started else None,
            predicted_class=label,
            anomaly_flag=bool(flag),
            alarm_active=state.alarm.active,
            alarm_started=started,
            score=score if known else None,
            decision_threshold=bundle.threshold,
            quality_status=status,
            evidence=self._evidence(row[0], moment) if flag else [],
            model_id=bundle.model_id,
            model_version=bundle.model_version,
            input_provenance=_INPUT_PROVENANCE[domain],
        )

    def _evidence(self, row: np.ndarray, moment: datetime) -> list[EvidenceReference]:
        """Sensors furthest from training normal. This points a reader to data and isn't a cause."""
        bundle = self.bundle
        spec = bundle.spec
        means = row[0::4].astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            deviation = np.abs(means - bundle.normal_median) / bundle.normal_scale
        ranked = np.argsort(-np.nan_to_num(deviation, nan=-1.0, posinf=-1.0))[:_TOP_EVIDENCE]
        start = moment - timedelta(seconds=spec.sample_s * (spec.window_samples - 1))
        return [
            EvidenceReference(
                tag=spec.sensors[i],
                measurement_definition_id=bundle.measurement_definitions.get(spec.sensors[i]),
                window_start=start,
                window_end=moment,
                deviation=float(deviation[i]) if np.isfinite(deviation[i]) else None,
            )
            for i in ranked
            if np.isfinite(means[i])
        ]
