"""Pydantic contracts for canonical records. They mirror database constraints, so bad records fail early."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProvenanceClass(StrEnum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    REPLAYED = "REPLAYED"
    SYNTHETIC = "SYNTHETIC"
    INFERRED = "INFERRED"


class ReferenceType(StrEnum):
    ABSOLUTE = "ABSOLUTE"
    GAUGE = "GAUGE"
    DIFFERENTIAL = "DIFFERENTIAL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CompatibilityClass(StrEnum):
    DIRECTLY_COMPATIBLE = "DIRECTLY_COMPATIBLE"
    CONDITIONALLY_COMPATIBLE = "CONDITIONALLY_COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class SpatialStatus(StrEnum):
    USABLE = "USABLE"
    QUARANTINED = "QUARANTINED"
    UNRESOLVED_DATUM = "UNRESOLVED_DATUM"
    NO_LOCATION = "NO_LOCATION"


class InstanceOrigin(StrEnum):
    REAL = "REAL"
    SIMULATED = "SIMULATED"
    HAND_DRAWN = "HAND_DRAWN"


class Canonical(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceAsset(Canonical):
    source_asset_id: str
    source_system_id: str
    parent_source_asset_id: str | None = None
    asset_type: str = Field(pattern="^(WELL|WELL_COMPLETION)$")
    external_identifier: str
    asset_name: str | None = None
    equipment_class_id: str
    operating_status: str | None = None
    reported_latitude: float | None = None
    reported_longitude: float | None = None
    reported_datum_label: str | None = None
    spatial_status: SpatialStatus
    attributes: dict[str, Any] = {}
    provenance_class: ProvenanceClass = ProvenanceClass.OBSERVED
    batch_id: str
    transformation_id: str
    source_record_key: str

    @model_validator(mode="after")
    def real_assets_are_observed(self) -> Self:
        if self.provenance_class is not ProvenanceClass.OBSERVED:
            raise ValueError("source assets are real records and must be OBSERVED")
        if self.spatial_status is SpatialStatus.USABLE and (
            self.reported_latitude is None or self.reported_longitude is None
        ):
            raise ValueError("a USABLE asset needs reported coordinates")
        return self


class HistoryRecord(Canonical):
    source_asset_id: str
    valid_from: date
    valid_to: date | None
    operator_code: str | None
    status_code: str | None
    well_type_code: str | None
    reported_latitude: float | None
    reported_longitude: float | None
    reported_datum_label: str | None
    attributes: dict[str, Any]
    provenance_class: ProvenanceClass = ProvenanceClass.OBSERVED
    batch_id: str
    transformation_id: str
    source_record_key: str


class ProductionRecord(Canonical):
    source_system_id: str
    reporting_entity_id: str
    reporting_grain: str = Field(pattern="^(WELL_COMPLETION|WELL|LEASE|OPERATOR)$")
    reporting_period: date
    product_kind: str
    reported_volume: int | None = Field(ge=0)
    unit_id: str
    unit_system: str
    pool_code: str
    operator_code: str
    days_produced: int | None = Field(ge=0, le=31)
    completion_status_code: str | None
    is_amended: bool | None
    source_effective_at: datetime
    source_modified_at: datetime | None
    original_record_uri: str
    provenance_class: ProvenanceClass = ProvenanceClass.OBSERVED
    batch_id: str
    transformation_id: str
    source_record_key: str

    @model_validator(mode="after")
    def period_is_first_of_month(self) -> Self:
        if self.reporting_period.day != 1:
            raise ValueError("reporting_period must be the first day of the production month")
        if self.provenance_class is not ProvenanceClass.OBSERVED:
            raise ValueError("production records are OBSERVED")
        return self


class TelemetryEvent(Canonical):
    event_id: str
    source_system_id: str
    source_instance_id: str
    source_asset_id: str | None
    source_event_label: int = Field(ge=0)
    source_event_class: str
    start_timestamp: datetime
    end_timestamp: datetime
    real_or_simulated_source: InstanceOrigin
    observation_count: int = Field(ge=0)
    parquet_uri: str
    dataset_version: str
    upstream_checksum: str
    provenance_class: ProvenanceClass
    batch_id: str
    transformation_id: str

    @model_validator(mode="after")
    def origin_rules(self) -> Self:
        real = self.real_or_simulated_source is InstanceOrigin.REAL
        if real != (self.source_asset_id is not None):
            raise ValueError("real instances need a source well and generated instances have none")
        expected = ProvenanceClass.OBSERVED if real else ProvenanceClass.SYNTHETIC
        if self.provenance_class is not expected:
            raise ValueError(f"{self.real_or_simulated_source} instances must be {expected}")
        if self.end_timestamp < self.start_timestamp:
            raise ValueError("end_timestamp precedes start_timestamp")
        return self


class Observation(Canonical):
    source_system_id: str
    source_record_id: str
    observed_at: datetime | None = None
    observation_type: str
    metric_name: str
    numeric_value: float | None = None
    unit_id: str | None
    quality_flag: str
    provenance_class: ProvenanceClass
    original_record_uri: str
    sensor_tag_id: str | None
    telemetry_event_id: str | None
    value_count: int | None = Field(default=None, ge=0)
    null_count: int | None = Field(default=None, ge=0)
    batch_id: str | None
    transformation_id: str


class SensorTag(Canonical):
    tag_id: str
    source_system_id: str
    native_tag_name: str
    canonical_metric: str | None = None
    equipment_position: str
    equipment_class_id: str
    physical_quantity: str
    unit_id: str
    pressure_reference_type: ReferenceType
    sampling_frequency: str | None = None
    mapping_status: str
    source_description: str

    @model_validator(mode="after")
    def reference_fits_quantity(self) -> Self:
        is_pressure = self.physical_quantity == "pressure"
        if is_pressure == (self.pressure_reference_type is ReferenceType.NOT_APPLICABLE):
            raise ValueError("pressure needs a reference type, including UNKNOWN; others do not")
        return self


class MeasurementDefinition(Canonical):
    measurement_definition_id: str
    equipment_class_id: str
    physical_quantity: str
    equipment_location: str
    reference_type: ReferenceType
    canonical_unit_id: str
    description: str


class SensorTagMapping(Canonical):
    tag_id: str
    measurement_definition_id: str
    equipment_class_id: str
    reference_type: ReferenceType
    source_system_id: str
    original_unit_id: str
    canonical_unit_id: str
    conversion_method: str
    data_quality_state: str
    mapping_status: str
    rationale: str


class CompatibilityAssessment(Canonical):
    assessment_id: str
    source_system_id: str
    subject_type: str = Field(pattern="^(VARIABLE|EVENT_CLASS)$")
    subject_id: str
    target_equipment_class_id: str
    classification: CompatibilityClass
    reasoning: str = Field(min_length=20)
    conditions: list[str] = []
    assessment_version: int
    assessed_on: date

    @model_validator(mode="after")
    def conditional_states_conditions(self) -> Self:
        conditional = self.classification is CompatibilityClass.CONDITIONALLY_COMPATIBLE
        if conditional and not self.conditions:
            raise ValueError("a conditional classification must state its conditions")
        return self


class ScenarioMapping(Canonical):
    scenario_id: str
    target_asset_id: str
    telemetry_event_id: str
    original_source_instance_id: str
    transformation_config: dict[str, Any]
    compatibility_assessment_id: str
    conditions_satisfied: list[str] | None = None
    mapping_provenance: ProvenanceClass
    replay_start_time: datetime | None = None

    @model_validator(mode="after")
    def mapping_is_never_observed(self) -> Self:
        allowed = {ProvenanceClass.REPLAYED, ProvenanceClass.SYNTHETIC}
        if self.mapping_provenance not in allowed:
            raise ValueError("a scenario mapping must be REPLAYED or SYNTHETIC")
        return self


class DataQualityException(Canonical):
    exception_type: str
    severity: str = Field(pattern="^(ERROR|WARNING|INFO)$")
    source_system_id: str
    batch_id: str
    dataset: str
    source_asset_id: str | None = None
    source_record_key: str
    field_name: str | None = None
    original_values: dict[str, Any]
    evidence: dict[str, Any]
    rule_id: str
    disposition: str
    status: str
    decision_rationale: str = Field(min_length=10)


class ReconciliationEvidence(Canonical):
    source_asset_id: str
    batch_id: str
    field_name: str
    channel_a: str
    value_a: str | None
    channel_b: str
    value_b: str | None
    outcome: str = Field(pattern="^(AGREE|CONFLICT|MISSING)$")
    channels_are_independent: bool
    method_version: str


_API = re.compile(r"^\d{2}-\d{3}-\d{5}$")


def well_id(api_number: str) -> str:
    if not _API.match(api_number):
        raise ValueError(f"not an API number: {api_number!r}")
    return f"nm_ocd:well:{api_number}"


def completion_id(api_number: str, pool_code: str) -> str:
    return f"nm_ocd:completion:{api_number}:{pool_code}"
