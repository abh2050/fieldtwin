"""Provenance tracking: record-level checks, plus an audit of the whole database."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from packages.domain.models import InstanceOrigin, ProvenanceClass


class ProvenanceError(ValueError):
    """A record or relationship with missing or incorrect provenance."""


def require_provenance(value: ProvenanceClass | str | None) -> ProvenanceClass:
    if value is None or value == "":
        raise ProvenanceError("a relationship can't be recorded without provenance")
    try:
        return ProvenanceClass(value)
    except ValueError as error:
        raise ProvenanceError(f"unknown provenance class {value!r}") from error


def require_simulated_is_synthetic(provenance: ProvenanceClass | str | None) -> None:
    """Simulator output is SYNTHETIC. Calling it anything else misrepresents it."""
    if require_provenance(provenance) is not ProvenanceClass.SYNTHETIC:
        raise ProvenanceError(f"simulated data can't be classified {provenance}")


def expected_instance_provenance(origin: InstanceOrigin) -> ProvenanceClass:
    return ProvenanceClass.OBSERVED if origin is InstanceOrigin.REAL else ProvenanceClass.SYNTHETIC


@dataclass(frozen=True)
class AuditFinding:
    name: str
    violations: int
    rule: str


_AUDIT = {
    "fictional_assets_not_synthetic": (
        "SELECT count(*) FROM assets WHERE provenance_class <> 'SYNTHETIC' OR NOT is_fictional",
        "Every fictional asset is SYNTHETIC",
    ),
    "source_assets_not_observed": (
        "SELECT count(*) FROM source_assets WHERE provenance_class <> 'OBSERVED'",
        "Every real source asset is OBSERVED",
    ),
    "3w_observation_linked_to_fictional_asset": (
        """SELECT count(*) FROM asset_observation_links l JOIN observations o USING (observation_id)
           WHERE l.asset_id IS NOT NULL AND o.source_system_id = 'petrobras_3w'""",
        "No 3W observation is linked to an AETHER asset",
    ),
    "3w_scenario_mapping": (
        """SELECT count(*) FROM scenario_mappings m JOIN telemetry_events e ON e.event_id = m.telemetry_event_id
           WHERE e.source_system_id = 'petrobras_3w'""",
        "No 3W event is mapped into an AETHER scenario",
    ),
    "benchmark_event_with_aether_scope": (
        """SELECT count(*) FROM shared_events WHERE domain = 'OFFSHORE_BENCHMARK'
           AND (target_asset_id IS NOT NULL OR scenario_id IS NOT NULL)""",
        "Benchmark events never name an AETHER asset or scenario",
    ),
    "simulated_series_not_synthetic": (
        """SELECT count(*) FROM observations
           WHERE source_system_id = 'aether_synthetic' AND provenance_class <> 'SYNTHETIC'""",
        "All simulated observations are SYNTHETIC",
    ),
    "simulated_series_with_real_source": (
        """SELECT count(*) FROM observations
           WHERE scenario_run_id IS NOT NULL AND source_system_id <> 'aether_synthetic'""",
        "Simulator runs produce only synthetic-source observations",
    ),
    "aether_observation_linked_to_real_asset": (
        """SELECT count(*) FROM asset_observation_links l JOIN observations o USING (observation_id)
           WHERE l.source_asset_id IS NOT NULL AND o.source_system_id = 'aether_synthetic'""",
        "Synthetic observations are never linked to real assets",
    ),
    "verified_identity_by_weak_method": (
        """SELECT count(*) FROM reconciliation_decisions WHERE verification_status = 'VERIFIED'
           AND relationship_type IN ('SAME_AS', 'COMPLETION_OF')
           AND method NOT IN ('AUTHORITATIVE_IDENTIFIER', 'HUMAN_REVIEW')""",
        "Verified identity rests only on identifiers or human review",
    ),
    "verified_inferred_decision": (
        """SELECT count(*) FROM reconciliation_decisions
           WHERE provenance_class = 'INFERRED' AND verification_status = 'VERIFIED'""",
        "Inferred relationships are never verified",
    ),
    "proximity_used_as_identity": (
        """SELECT count(*) FROM reconciliation_decisions
           WHERE method = 'GEOSPATIAL_PROXIMITY' AND relationship_type = 'SAME_AS'
           AND verification_status <> 'REJECTED'""",
        "Geospatial proximity never establishes identity",
    ),
    "real_decision_targets_fictional_asset": (
        """SELECT count(*) FROM reconciliation_decisions
           WHERE subject_type = 'SOURCE_ASSET' AND object_type = 'ASSET'""",
        "No decision relates a real asset to a fictional one",
    ),
}


def audit_provenance(conn: psycopg.Connection) -> list[AuditFinding]:
    """Count rows that break each rule. Constraints should keep every count at zero."""
    findings = []
    for name, (sql, rule) in _AUDIT.items():
        row = conn.execute(sql).fetchone()
        findings.append(AuditFinding(name, int(row[0]) if row else 0, rule))
    return findings
