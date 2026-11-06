"""Streaming inference contracts. They have no field for fault truth, and extra fields are refused."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InputDomain(StrEnum):
    OFFSHORE_BENCHMARK = "OFFSHORE_BENCHMARK"
    AETHER_SYNTHETIC = "AETHER_SYNTHETIC"


class SensorQuality(StrEnum):
    GOOD = "GOOD"
    BAD_COMM_LOST = "BAD_COMM_LOST"
    BAD_NOT_MEASURABLE = "BAD_NOT_MEASURABLE"
    UNKNOWN = "UNKNOWN"


class QualityStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SensorObservation(Strict):
    tag: str = Field(min_length=1)
    timestamp: datetime
    value: float | None
    quality: SensorQuality

    @model_validator(mode="after")
    def no_truth_channel(self) -> Self:
        if self.tag.lower().startswith(("truth", "diag_", "class", "label", "severity", "onset")):
            raise ValueError(f"{self.tag} isn't a sensor. Fault truth can't enter inference.")
        return self


class InferenceRequest(Strict):
    asset_id: str = Field(min_length=1)
    domain: InputDomain
    measurement_definitions: dict[str, str]
    observations: list[SensorObservation]
    model_id: str
    model_version: str


class EvidenceReference(Strict):
    tag: str
    measurement_definition_id: str | None
    window_start: datetime
    window_end: datetime
    deviation: float | None


class Prediction(Strict):
    prediction_id: str
    asset_id: str
    event_timestamp: datetime
    detection_timestamp: datetime | None
    predicted_class: str
    anomaly_flag: bool
    alarm_active: bool
    alarm_started: bool
    score: float | None
    decision_threshold: float
    quality_status: QualityStatus
    evidence: list[EvidenceReference]
    model_id: str
    model_version: str
    provenance_class: str = "INFERRED"
    input_provenance: str
