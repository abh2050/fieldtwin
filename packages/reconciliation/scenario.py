"""Experimental scenario mapping. A scenario is declared, and it never becomes observed fact."""

from __future__ import annotations

from packages.domain.models import ProvenanceClass
from packages.domain.reconciliation import (
    EntityType,
    Method,
    Module,
    ReconciliationDecision,
    Relationship,
    Status,
)
from packages.domain.semantics import SemanticError

ALLOWED_FLOW_CONNECTIONS = {
    ("WELL_PAD", "FEEDS", "GATHERING_NETWORK"),
    ("GATHERING_NETWORK", "FEEDS", "COMPRESSOR"),
    ("WELL", "FEEDS", "GATHERING_SEGMENT"),
    ("GATHERING_SEGMENT", "FEEDS", "GATHERING_SEGMENT"),
    ("GATHERING_SEGMENT", "FEEDS", "COMPRESSION_STATION"),
}
SYNTHETIC_SOURCE = "aether_synthetic"


class DomainBoundaryError(SemanticError):
    """An attempt to apply one physical system's telemetry to a different physical system."""


class EquipmentRelationshipError(SemanticError):
    """A connection between equipment that the facility doesn't allow."""


def require_scenario_source(source_system_id: str, target_domain: str) -> None:
    """AETHER scenarios use synthetic telemetry only. Nothing else is mapped onto them."""
    if target_domain == "FICTIONAL_ONSHORE" and source_system_id != SYNTHETIC_SOURCE:
        raise DomainBoundaryError(
            f"{source_system_id} can't be mapped onto a fictional onshore asset. "
            "AETHER scenarios use synthetic telemetry."
        )


def validate_equipment_relationship(source_type: str, relationship: str, target_type: str) -> None:
    if (source_type, relationship, target_type) not in ALLOWED_FLOW_CONNECTIONS:
        raise EquipmentRelationshipError(
            f"{source_type} {relationship} {target_type} isn't an allowed connection"
        )


def assignment_decision(
    run_id: str, asset_id: str, config_sha256: str, seed: int, algorithm: str
) -> ReconciliationDecision:
    """Record that a simulator run is assigned to a fictional asset by declaration, not discovery."""
    return ReconciliationDecision(
        module=Module.SCENARIO,
        subject_type=EntityType.SCENARIO_RUN,
        subject_id=run_id,
        object_type=EntityType.ASSET,
        object_id=asset_id,
        relationship_type=Relationship.EXPERIMENTAL_ASSIGNMENT,
        method=Method.DECLARED_BY_SCENARIO_CONFIG,
        evidence={"config_sha256": config_sha256, "random_seed": seed},
        verification_status=Status.UNVERIFIED,
        provenance_class=ProvenanceClass.SYNTHETIC,
        algorithm_version=algorithm,
    )
