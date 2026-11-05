"""Run the reconciliation engine on canonical data. Safe to re-run for one algorithm version."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import yaml

from packages.domain.models import ProvenanceClass, ReferenceType, SpatialStatus
from packages.domain.reconciliation import (
    EntityType,
    Method,
    Module,
    ReconciliationDecision,
    Relationship,
    Status,
)
from packages.reconciliation.geospatial import Located, proximity_decision
from packages.reconciliation.identity import RecordRef, match_identity
from packages.reconciliation.provenance import audit_provenance
from packages.reconciliation.review import store_decisions
from packages.reconciliation.semantic import (
    DefinitionView,
    TagView,
    native_decision,
    rejected_cross_domain_decision,
)
from packages.repositories.database import REPO_ROOT, connect

RULES_PATH = REPO_ROOT / "config" / "rules" / "reconciliation.yaml"
OCD_CHANNEL = "ocd_ftp_wellhistory"


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _already_run(conn: psycopg.Connection, module: Module, algorithm: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM reconciliation_decisions WHERE module = %s AND algorithm_version = %s LIMIT 1",
        (module.value, algorithm),
    ).fetchone()
    return row is not None


def identity_decisions(
    conn: psycopg.Connection, rules: dict[str, Any]
) -> list[ReconciliationDecision]:
    algorithm = rules["algorithms"]["identity"]
    authoritative = set(rules["identity"]["authoritative_identifier_types"]["nm_ocd"])
    decisions = []

    # Each OCD well in the ArcGIS registry against the FTP well history, joined on API number only.
    for asset_id, api, name, batch, history_api, history_name in conn.execute(
        """SELECT w.source_asset_id, w.external_identifier, w.asset_name, w.batch_id,
                  h.attributes->>'api', h.attributes->>'well_name'
           FROM source_assets w
           LEFT JOIN LATERAL (
             SELECT attributes FROM source_asset_history
             WHERE source_asset_id = w.source_asset_id ORDER BY valid_from DESC LIMIT 1
           ) h ON true
           WHERE w.source_system_id = 'nm_ocd' AND w.asset_type = 'WELL'
           ORDER BY w.source_asset_id"""
    ):
        registry = RecordRef(EntityType.SOURCE_ASSET, asset_id, "nm_ocd", {"API_NUMBER": api}, name)
        history = RecordRef(
            EntityType.SOURCE_RECORD,
            f"{OCD_CHANNEL}:{api}",
            "nm_ocd",
            {"API_NUMBER": history_api} if history_api else {},
            history_name,
        )
        decisions.append(match_identity(registry, history, authoritative, algorithm, batch))

    # A completion belongs to its well because the API number is part of the reported key.
    for completion, parent, external, batch in conn.execute(
        """SELECT source_asset_id, parent_source_asset_id, external_identifier, batch_id
           FROM source_assets WHERE asset_type = 'WELL_COMPLETION' ORDER BY source_asset_id"""
    ):
        decisions.append(
            ReconciliationDecision(
                module=Module.IDENTITY,
                subject_type=EntityType.SOURCE_ASSET,
                subject_id=completion,
                object_type=EntityType.SOURCE_ASSET,
                object_id=parent,
                relationship_type=Relationship.COMPLETION_OF,
                method=Method.AUTHORITATIVE_IDENTIFIER,
                evidence={"reported_key": external},
                verification_status=Status.VERIFIED,
                provenance_class=ProvenanceClass.DERIVED,
                algorithm_version=algorithm,
                batch_id=batch,
            )
        )

    # 3W wells are anonymized offshore wells, and no identifier connects them to New Mexico wells.
    row = conn.execute(
        "SELECT count(*) FROM source_assets WHERE source_system_id = 'petrobras_3w'"
    ).fetchone()
    decisions.append(
        ReconciliationDecision(
            module=Module.IDENTITY,
            subject_type=EntityType.SOURCE_SYSTEM,
            subject_id="petrobras_3w",
            object_type=EntityType.SOURCE_SYSTEM,
            object_id="nm_ocd",
            relationship_type=Relationship.NO_CROSSWALK,
            method=Method.NO_SHARED_IDENTIFIER,
            evidence={
                "reason": "Anonymized offshore wells share no identifier with New Mexico wells.",
                "3w_wells": row[0] if row else 0,
            },
            verification_status=Status.UNRESOLVED,
            provenance_class=ProvenanceClass.DERIVED,
            algorithm_version=algorithm,
        )
    )
    return decisions


def semantic_decisions(
    conn: psycopg.Connection, rules: dict[str, Any]
) -> list[ReconciliationDecision]:
    algorithm = rules["algorithms"]["semantic"]
    units = {r[0] for r in conn.execute("SELECT unit_id FROM units")}
    definitions = [
        DefinitionView(r[0], r[1], r[2], r[3], ReferenceType(r[4]))
        for r in conn.execute(
            """SELECT measurement_definition_id, equipment_class_id, physical_quantity,
                      canonical_unit_id, reference_type FROM measurement_definitions"""
        )
    ]
    by_id = {d.definition_id: d for d in definitions}
    decisions = []
    for tag_id, system, equipment, quantity, unit, reference, definition_id in conn.execute(
        """SELECT t.tag_id, t.source_system_id, t.equipment_class_id, t.physical_quantity, t.unit_id,
                  t.pressure_reference_type, m.measurement_definition_id
           FROM sensor_tags t JOIN sensor_tag_mappings m USING (tag_id) ORDER BY t.tag_id"""
    ):
        tag = TagView(tag_id, system, equipment, quantity, unit, ReferenceType(reference))
        synthetic = system == "aether_synthetic"
        decisions.append(
            native_decision(
                tag,
                by_id[definition_id],
                units,
                algorithm,
                Method.DECLARED_SYNTHETIC_DESIGN
                if synthetic
                else Method.PUBLISHED_DEFINITION_SAME_CLASS,
                ProvenanceClass.SYNTHETIC if synthetic else ProvenanceClass.DERIVED,
            )
        )
        if system == "petrobras_3w":
            # Try every AETHER definition of the same quantity. The attempt must fail and be recorded.
            for definition in definitions:
                on_aether = definition.equipment_class_id.startswith("AETHER_")
                if on_aether and definition.physical_quantity == quantity:
                    decisions.append(
                        rejected_cross_domain_decision(tag, definition, units, algorithm)
                    )
    return decisions


def geospatial_decisions(
    conn: psycopg.Connection, rules: dict[str, Any], radius_m: float | None = None
) -> list[ReconciliationDecision]:
    """Pairs of usable wells inside the screening radius, computed by PostGIS on geography."""
    algorithm = rules["algorithms"]["geospatial"]
    radius = radius_m if radius_m is not None else rules["geospatial"]["well_proximity_radius_m"]
    decisions = []
    for a_id, a_y, a_x, b_id, b_y, b_x, distance, batch in conn.execute(
        """SELECT a.source_asset_id, ST_Y(a.geometry), ST_X(a.geometry),
                  b.source_asset_id, ST_Y(b.geometry), ST_X(b.geometry),
                  ST_Distance(a.geometry::geography, b.geometry::geography), s.batch_id
           FROM v_spatially_usable_source_assets a
           JOIN source_assets s ON s.source_asset_id = a.source_asset_id
           JOIN v_spatially_usable_source_assets b
             ON a.source_asset_id < b.source_asset_id
            AND ST_DWithin(a.geometry::geography, b.geometry::geography, %s)
           ORDER BY 1, 4""",
        (radius,),
    ):
        decisions.append(
            proximity_decision(
                Located(EntityType.SOURCE_ASSET, a_id, a_y, a_x, SpatialStatus.USABLE),
                Located(EntityType.SOURCE_ASSET, b_id, b_y, b_x, SpatialStatus.USABLE),
                distance,
                radius,
                algorithm,
                batch_id=batch,
            )
        )
    return decisions


def reconcile_all(conn: psycopg.Connection, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run each module once per algorithm version, in one transaction."""
    rules = rules or load_rules()
    results: dict[str, Any] = {}
    steps = (
        (Module.IDENTITY, "identity", identity_decisions),
        (Module.SEMANTIC, "semantic", semantic_decisions),
        (Module.GEOSPATIAL, "geospatial", geospatial_decisions),
    )
    with conn.transaction():
        for module, key, build in steps:
            algorithm = rules["algorithms"][key]
            if _already_run(conn, module, algorithm):
                results[key] = "already_run"
            else:
                results[key] = store_decisions(conn, build(conn, rules))
    findings = audit_provenance(conn)
    results["provenance_audit_violations"] = sum(f.violations for f in findings)
    results["provenance_audit_rules"] = len(findings)
    return results


def main() -> int:
    with connect() as conn:
        results = reconcile_all(conn)
    print(json.dumps(results, indent=2))
    return 1 if results["provenance_audit_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
