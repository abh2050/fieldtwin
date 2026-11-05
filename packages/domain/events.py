"""The shared event contract. Both domains use one shape and never share assets."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ProvenanceClass

SCHEMA_VERSION = 1


class EventDomain(StrEnum):
    AETHER_SYNTHETIC = "AETHER_SYNTHETIC"
    OFFSHORE_BENCHMARK = "OFFSHORE_BENCHMARK"


class EventKind(StrEnum):
    SOURCE_LABEL = "SOURCE_LABEL"
    KNOWN_SYNTHETIC_ONSET = "KNOWN_SYNTHETIC_ONSET"
    INTEGRATION_PROOF_RULE = "INTEGRATION_PROOF_RULE"


class SharedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    schema_version: int = SCHEMA_VERSION
    domain: EventDomain
    event_kind: EventKind
    event_class: str
    source_system_id: str
    telemetry_event_id: str | None = None
    scenario_id: str | None = None
    scenario_run_id: str | None = None
    target_asset_id: str | None = None
    affected_asset_id: str | None = None
    onset_offset_s: int | None = Field(default=None, ge=0)
    evidence: dict[str, Any] = Field(min_length=1)
    provenance_class: ProvenanceClass
    transformation_id: str

    @model_validator(mode="after")
    def domains_stay_separate(self) -> Self:
        if self.domain is EventDomain.AETHER_SYNTHETIC:
            if self.provenance_class is not ProvenanceClass.SYNTHETIC:
                raise ValueError("AETHER events are SYNTHETIC")
            if self.source_system_id != "aether_synthetic":
                raise ValueError("AETHER events come only from the synthetic source")
            if not (self.scenario_id and self.scenario_run_id and self.target_asset_id):
                raise ValueError("AETHER events need a scenario, a run, and a target asset")
            if self.telemetry_event_id or self.event_kind is EventKind.SOURCE_LABEL:
                raise ValueError("AETHER events can't carry a source telemetry event")
        else:
            if self.target_asset_id or self.affected_asset_id:
                raise ValueError("benchmark events can't name an AETHER asset")
            if self.scenario_id or self.scenario_run_id:
                raise ValueError("benchmark events can't belong to an AETHER scenario")
            if not self.telemetry_event_id or self.event_kind is not EventKind.SOURCE_LABEL:
                raise ValueError("benchmark events keep their source telemetry event and label")
            if self.source_system_id != "petrobras_3w":
                raise ValueError("this benchmark domain is Petrobras 3W")
            if self.provenance_class not in (ProvenanceClass.DERIVED, ProvenanceClass.SYNTHETIC):
                raise ValueError(
                    "benchmark events are DERIVED from real or SYNTHETIC from generated"
                )
        return self


class PrioritizationInput(BaseModel):
    """What a later inspection or work-order workflow receives. It holds no score or decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    scenario_id: str
    scenario_run_id: str
    asset_id: str
    affected_asset_id: str
    event_kind: EventKind
    evidence: dict[str, Any] = Field(min_length=1)
    provenance_class: ProvenanceClass = ProvenanceClass.SYNTHETIC
    disclosure: str = Field(min_length=20)
    priority_score: None = None
    recommended_action: None = None

    @classmethod
    def from_event(cls, event: SharedEvent, disclosure: str) -> PrioritizationInput:
        if event.domain is not EventDomain.AETHER_SYNTHETIC:
            raise ValueError("only AETHER scenario events can enter AETHER prioritization")
        return cls(
            event_id=event.event_id,
            scenario_id=str(event.scenario_id),
            scenario_run_id=str(event.scenario_run_id),
            asset_id=str(event.target_asset_id),
            affected_asset_id=str(event.affected_asset_id),
            event_kind=event.event_kind,
            evidence=event.evidence,
            disclosure=disclosure,
        )
