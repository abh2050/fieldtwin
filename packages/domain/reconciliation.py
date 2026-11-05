"""Typed reconciliation and relationship contracts. They repeat the key database rules for early errors."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ProvenanceClass


class Module(StrEnum):
    IDENTITY = "IDENTITY"
    SEMANTIC = "SEMANTIC"
    GEOSPATIAL = "GEOSPATIAL"
    SCENARIO = "SCENARIO"


class EntityType(StrEnum):
    SOURCE_ASSET = "SOURCE_ASSET"
    ASSET = "ASSET"
    SOURCE_RECORD = "SOURCE_RECORD"
    SOURCE_SYSTEM = "SOURCE_SYSTEM"
    SENSOR_TAG = "SENSOR_TAG"
    OBSERVATION = "OBSERVATION"
    SCENARIO_RUN = "SCENARIO_RUN"
    MEASUREMENT_DEFINITION = "MEASUREMENT_DEFINITION"


class Relationship(StrEnum):
    SAME_AS = "SAME_AS"
    COMPLETION_OF = "COMPLETION_OF"
    NO_CROSSWALK = "NO_CROSSWALK"
    SAME_MEASUREMENT = "SAME_MEASUREMENT"
    PROXIMITY_CANDIDATE = "PROXIMITY_CANDIDATE"
    EMISSION_NEAR = "EMISSION_NEAR"
    EXPERIMENTAL_ASSIGNMENT = "EXPERIMENTAL_ASSIGNMENT"


class Method(StrEnum):
    AUTHORITATIVE_IDENTIFIER = "AUTHORITATIVE_IDENTIFIER"
    NO_SHARED_IDENTIFIER = "NO_SHARED_IDENTIFIER"
    NAME_SIMILARITY = "NAME_SIMILARITY"
    GEOSPATIAL_PROXIMITY = "GEOSPATIAL_PROXIMITY"
    UNIT_SIMILARITY = "UNIT_SIMILARITY"
    PUBLISHED_DEFINITION_SAME_CLASS = "PUBLISHED_DEFINITION_SAME_CLASS"
    DECLARED_SYNTHETIC_DESIGN = "DECLARED_SYNTHETIC_DESIGN"
    COMPATIBILITY_VALIDATION = "COMPATIBILITY_VALIDATION"
    DECLARED_BY_SCENARIO_CONFIG = "DECLARED_BY_SCENARIO_CONFIG"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class Status(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"


WEAK_IDENTITY_METHODS = {
    Method.NAME_SIMILARITY,
    Method.GEOSPATIAL_PROXIMITY,
    Method.UNIT_SIMILARITY,
}
PROXIMITY_RELATIONSHIPS = {Relationship.PROXIMITY_CANDIDATE, Relationship.EMISSION_NEAR}


class ReconciliationDecision(BaseModel):
    """One reconciliation outcome. `decided_at` is set by the database when the row is stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    module: Module
    subject_type: EntityType
    subject_id: str = Field(min_length=1)
    object_type: EntityType | None = None
    object_id: str | None = None
    relationship_type: Relationship
    method: Method
    evidence: dict[str, Any] = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    uncertainty: dict[str, Any] | None = None
    verification_status: Status
    provenance_class: ProvenanceClass
    algorithm_version: str = Field(pattern=r"@[0-9]+$")
    batch_id: str | None = None

    @model_validator(mode="after")
    def enforce_boundaries(self) -> Self:
        if (self.object_type is None) != (self.object_id is None):
            raise ValueError("object_type and object_id must be set together")
        types = {self.subject_type, self.object_type}
        if {EntityType.SOURCE_ASSET, EntityType.ASSET} <= types:
            raise ValueError("a real source asset can't be related directly to a fictional asset")
        if self.relationship_type is Relationship.SAME_AS:
            if EntityType.ASSET in types:
                raise ValueError("identity can't involve a fictional asset")
            if (
                self.method in WEAK_IDENTITY_METHODS
                and self.verification_status is not Status.REJECTED
            ):
                raise ValueError(f"{self.method} can't establish identity")
        verified = self.verification_status is Status.VERIFIED
        if verified and self.relationship_type in (
            Relationship.SAME_AS,
            Relationship.COMPLETION_OF,
        ):
            if self.method is not Method.AUTHORITATIVE_IDENTIFIER:
                raise ValueError("verified identity needs an authoritative identifier")
        if self.provenance_class is ProvenanceClass.INFERRED and verified:
            raise ValueError("an inferred relationship can't be verified")
        if self.relationship_type in PROXIMITY_RELATIONSHIPS:
            if verified or self.provenance_class is not ProvenanceClass.INFERRED:
                raise ValueError("proximity is an inferred candidate and is never verified")
            if self.confidence is not None:
                raise ValueError("distance is not a probability, so proximity has no confidence")
        if self.relationship_type is Relationship.EXPERIMENTAL_ASSIGNMENT:
            allowed = {ProvenanceClass.REPLAYED, ProvenanceClass.SYNTHETIC}
            if verified or self.provenance_class not in allowed:
                raise ValueError("an experimental assignment can't be verified or observed")
        return self
