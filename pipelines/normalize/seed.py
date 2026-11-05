"""Seed reference data into a migrated database. Safe to re-run."""

from __future__ import annotations

import configparser
import json
from pathlib import Path
from typing import Any

import psycopg
import yaml

from packages.domain.models import (
    CompatibilityAssessment,
    MeasurementDefinition,
    ReferenceType,
    SensorTag,
    SensorTagMapping,
)
from packages.repositories.database import REPO_ROOT, connect, scalar

W3_SOURCE = "petrobras_3w"
FIXTURE_INI = REPO_ROOT / "data" / "fixtures" / "petrobras_3w" / "dataset.ini"


def contract(name: str) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / "data_contracts" / "semantic_mappings" / name).read_text())


def read_ini() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(FIXTURE_INI)
    return parser


def _insert(conn: psycopg.Connection, table: str, rows: list[dict[str, Any]], key: str) -> int:
    if not rows:
        return 0
    columns = list(rows[0])
    placeholders = ", ".join(f"%({c})s" for c in columns)
    names = ", ".join(columns)
    sql = f"INSERT INTO {table} ({names}) VALUES ({placeholders}) ON CONFLICT ({key}) DO NOTHING"
    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)
    return len(rows)


def _source_systems(root: Path) -> list[dict[str, Any]]:
    rows = []
    for name in ("nm_ocd", "petrobras_3w"):
        config = yaml.safe_load((root / "config" / "sources" / f"{name}.yaml").read_text())
        rows.append(
            {
                "source_system_id": config["source_system_id"],
                "provider": config["provider"],
                "source_url": config["source_url"],
                "license": config["license"]["explicit_license"],
                "usage_constraints": config["license"]["usage_constraints"],
                "is_project_generated": False,
            }
        )
    return rows


def build_semantics() -> tuple[
    list[SensorTag], list[MeasurementDefinition], list[SensorTagMapping]
]:
    """3W tags map only to definitions of their own offshore class, and pressure stays UNKNOWN."""
    compatibility = contract("3w_aether_compatibility.yaml")
    descriptions = read_ini()["PARQUET_FILE_PROPERTIES"]
    source_class = compatibility["source_equipment_class_id"]
    tags, definitions, mappings = [], [], []
    for variable in compatibility["variables"]:
        if "quantity" not in variable:
            continue
        native = variable["tag"]
        is_pressure = variable["quantity"] == "pressure"
        reference = ReferenceType.UNKNOWN if is_pressure else ReferenceType.NOT_APPLICABLE
        tag = f"{W3_SOURCE}:{native}"
        definition = f"offshore_subsea_well.{native}"
        tags.append(
            SensorTag(
                tag_id=tag,
                source_system_id=W3_SOURCE,
                native_tag_name=native,
                equipment_position=variable["location"],
                equipment_class_id=source_class,
                physical_quantity=variable["quantity"],
                unit_id=variable["unit"],
                pressure_reference_type=reference,
                sampling_frequency="1 s median in the acquired batch",
                mapping_status="VERIFIED",
                source_description=descriptions[native],
            )
        )
        definitions.append(
            MeasurementDefinition(
                measurement_definition_id=definition,
                equipment_class_id=source_class,
                physical_quantity=variable["quantity"],
                equipment_location=variable["location"],
                reference_type=reference,
                canonical_unit_id=variable["unit"],
                description=descriptions[native],
            )
        )
        mappings.append(
            SensorTagMapping(
                tag_id=tag,
                measurement_definition_id=definition,
                equipment_class_id=source_class,
                reference_type=reference,
                source_system_id=W3_SOURCE,
                original_unit_id=variable["unit"],
                canonical_unit_id=variable["unit"],
                conversion_method="IDENTITY",
                data_quality_state="SEMANTICS_INCOMPLETE" if is_pressure else "SEMANTICS_COMPLETE",
                mapping_status="UNRESOLVED" if is_pressure else "VERIFIED",
                rationale="Same physical class and unit. Pressure reference type is not stated by the source."
                if is_pressure
                else "Same physical class and unit.",
            )
        )
    return tags, definitions, mappings


def build_assessments() -> list[CompatibilityAssessment]:
    data = contract("3w_aether_compatibility.yaml")
    assessments = []
    for subject_type, entries, key in (
        ("VARIABLE", data["variables"], "tag"),
        ("EVENT_CLASS", data["events"], "event"),
    ):
        for entry in entries:
            assessments.append(
                CompatibilityAssessment(
                    assessment_id=f"3w-aether:{subject_type}:{entry[key]}:v{data['assessment_version']}",
                    source_system_id=data["source_system_id"],
                    subject_type=subject_type,
                    subject_id=entry[key],
                    target_equipment_class_id=data["target_equipment_class_id"],
                    classification=entry["classification"],
                    reasoning=entry["reasoning"],
                    conditions=entry.get("conditions", []),
                    assessment_version=data["assessment_version"],
                    assessed_on=data["assessed_on"],
                )
            )
    return assessments


def seed_facility(conn: psycopg.Connection, root: Path) -> None:
    config = yaml.safe_load((root / "config" / "facility" / "aether_field.yaml").read_text())
    facility = config["facility"]
    _insert(
        conn,
        "facilities",
        [
            {
                "facility_id": facility["facility_id"],
                "facility_name": facility["facility_name"],
                "facility_type": facility["facility_type"],
                "region": facility["region"],
                "is_fictional": facility["is_fictional"],
                "disclosure": facility["disclosure"].strip(),
            }
        ],
        "facility_id",
    )
    transformation = "aether.facility_config.to_assets@1"

    def asset(asset_id, parent, kind, name, equipment):
        return {
            "asset_id": asset_id,
            "facility_id": facility["facility_id"],
            "parent_asset_id": parent,
            "asset_type": kind,
            "asset_name": name,
            "equipment_class_id": equipment,
            "is_fictional": True,
            "provenance_class": "SYNTHETIC",
            "transformation_id": transformation,
        }

    assets, parts = [], config["assets"]
    relationships = []
    for pad in parts["well_pads"]:
        assets.append(
            asset(pad["asset_id"], None, "WELL_PAD", pad["asset_name"], "AETHER_WELL_PAD")
        )
    for pad in parts["well_pads"]:
        for well in pad["wells"]:
            assets.append(
                asset(well, pad["asset_id"], "WELL", f"Well {well}", "AETHER_ONSHORE_GAS_WELL")
            )
    gathering = parts["gathering_network"]
    assets.append(
        asset(
            gathering["asset_id"],
            None,
            "GATHERING_NETWORK",
            gathering["asset_name"],
            "AETHER_GATHERING",
        )
    )
    for segment in gathering["gathering_segments"]:
        assets.append(
            asset(segment, gathering["asset_id"], "GATHERING_SEGMENT", segment, "AETHER_GATHERING")
        )
    for valve in gathering["isolation_valves"]:
        assets.append(
            asset(valve, gathering["asset_id"], "ISOLATION_VALVE", valve, "AETHER_GATHERING")
        )
    station = parts["compression_station"]
    assets.append(
        asset(
            station["asset_id"],
            None,
            "COMPRESSION_STATION",
            station["asset_name"],
            "AETHER_COMPRESSOR",
        )
    )
    for compressor in station["compressors"]:
        assets.append(
            asset(compressor, station["asset_id"], "COMPRESSOR", compressor, "AETHER_COMPRESSOR")
        )
        relationships.append(
            {
                "source_asset_id": gathering["asset_id"],
                "target_asset_id": compressor,
                "relationship_type": "FEEDS",
                "evidence_type": "FACILITY_CONFIG",
                "provenance_class": "SYNTHETIC",
            }
        )
    operations = parts["field_operations"]
    assets.append(
        asset(
            operations["asset_id"],
            None,
            "FIELD_OPERATIONS",
            operations["asset_name"],
            "AETHER_FIELD_OPERATIONS",
        )
    )
    _insert(conn, "assets", assets, "asset_id")
    for pad in parts["well_pads"]:
        relationships.append(
            {
                "source_asset_id": pad["asset_id"],
                "target_asset_id": gathering["asset_id"],
                "relationship_type": "FEEDS",
                "evidence_type": "FACILITY_CONFIG",
                "provenance_class": "SYNTHETIC",
            }
        )
    if not conn.execute("SELECT 1 FROM asset_relationships LIMIT 1").fetchone():
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO asset_relationships
                   (source_asset_id, target_asset_id, relationship_type, evidence_type, provenance_class)
                   VALUES (%(source_asset_id)s, %(target_asset_id)s, %(relationship_type)s,
                           %(evidence_type)s, %(provenance_class)s)""",
                relationships,
            )


def seed(conn: psycopg.Connection, root: Path = REPO_ROOT) -> dict[str, int]:
    """Load reference data. Existing keys are left alone, so a re-run changes nothing."""
    reference = contract("reference_data.yaml")
    compatibility = contract("3w_aether_compatibility.yaml")
    units_contract = contract("ocd_production_units.yaml")
    counts: dict[str, int] = {}

    systems = _source_systems(root) + [
        {
            "source_system_id": s["id"],
            "provider": s["provider"],
            "source_url": s["source_url"],
            "license": s["license"],
            "usage_constraints": s["usage_constraints"],
            "is_project_generated": s["is_project_generated"],
        }
        for s in reference["source_systems"]
    ]
    counts["source_systems"] = _insert(conn, "source_systems", systems, "source_system_id")
    counts["units"] = _insert(conn, "units", reference["units"], "unit_id")
    counts["unit_conversions"] = _insert(
        conn,
        "unit_conversions",
        [
            {
                "from_unit_id": c["from"],
                "to_unit_id": c["to"],
                "physical_quantity": c["quantity"],
                "factor": c["factor"],
                "term": c["term"],
                "method": c["method"],
            }
            for c in reference["unit_conversions"]
        ],
        "from_unit_id, to_unit_id",
    )
    counts["equipment_classes"] = _insert(
        conn,
        "equipment_classes",
        [
            {
                "equipment_class_id": c["id"],
                "name": c["name"],
                "domain": c["domain"],
                "description": c["description"],
                "basis": c["basis"],
            }
            for c in reference["equipment_classes"]
        ],
        "equipment_class_id",
    )
    counts["transformations"] = _insert(
        conn,
        "transformations",
        [
            {
                "transformation_id": t["id"],
                "name": t["name"],
                "version": t["version"],
                "code_reference": t["code"],
                "description": t["description"],
                "input_provenance": t["inputs"],
                "output_provenance": t["output"],
                "alters_values": t["alters"],
            }
            for t in reference["transformations"]
        ],
        "transformation_id",
    )

    tags, definitions, mappings = build_semantics()
    aether = [
        MeasurementDefinition(
            measurement_definition_id=m["id"],
            equipment_class_id="AETHER_ONSHORE_GAS_WELL",
            physical_quantity=m["quantity"],
            equipment_location=m["location"],
            reference_type=m["reference"],
            canonical_unit_id=m["unit"],
            description=f"Fictional design assumption: {m['location']}.",
        )
        for m in reference["aether_measurements"]
    ]
    counts["measurement_definitions"] = _insert(
        conn,
        "measurement_definitions",
        [d.model_dump(mode="json") for d in definitions + aether],
        "measurement_definition_id",
    )
    capabilities = [
        {
            "equipment_class_id": d.equipment_class_id,
            "measurement_definition_id": d.measurement_definition_id,
            "capability": "SOURCE_REPORTED",
            "basis": "Published in 3W dataset.ini",
        }
        for d in definitions
    ] + [
        {
            "equipment_class_id": "AETHER_ONSHORE_GAS_WELL",
            "measurement_definition_id": m["id"],
            "capability": m["capability"],
            "basis": "Fictional design assumption in config/facility/aether_field.yaml",
        }
        for m in reference["aether_measurements"]
    ]
    counts["equipment_measurement_capabilities"] = _insert(
        conn,
        "equipment_measurement_capabilities",
        capabilities,
        "equipment_class_id, measurement_definition_id",
    )
    counts["sensor_tags"] = _insert(
        conn, "sensor_tags", [t.model_dump(mode="json") for t in tags], "tag_id"
    )
    if not conn.execute("SELECT 1 FROM sensor_tag_mappings LIMIT 1").fetchone():
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO sensor_tag_mappings (tag_id, measurement_definition_id, equipment_class_id,
                     reference_type, source_system_id, original_unit_id, canonical_unit_id, conversion_method,
                     data_quality_state, mapping_status, rationale)
                   VALUES (%(tag_id)s, %(measurement_definition_id)s, %(equipment_class_id)s, %(reference_type)s,
                     %(source_system_id)s, %(original_unit_id)s, %(canonical_unit_id)s, %(conversion_method)s,
                     %(data_quality_state)s, %(mapping_status)s, %(rationale)s)""",
                [m.model_dump(mode="json") for m in mappings],
            )
    counts["sensor_tag_mappings"] = len(mappings)

    counts["production_unit_rules"] = _insert(
        conn,
        "production_unit_rules",
        [
            {
                "source_system_id": units_contract["source_system_id"],
                "product_kind": r["product_kind"],
                "unit_id": r["unit_id"],
                "product_scope": r["product_scope"],
                "base_conditions": r["base_conditions"],
                "verification_status": r["verification_status"],
                "evidence": json.dumps(r["evidence"]),
            }
            for r in units_contract["rules"]
        ],
        "source_system_id, product_kind",
    )

    parser = read_ini()
    classes = []
    for event in compatibility["events"]:
        section = parser[event["event"]]
        classes.append(
            {
                "source_system_id": W3_SOURCE,
                "event_label": int(section["LABEL"]),
                "event_name": event["event"],
                "description": section["DESCRIPTION"],
                "has_transient": {"True": True, "False": False}.get(section.get("TRANSIENT", "")),
            }
        )
    counts["source_event_classes"] = _insert(
        conn, "source_event_classes", classes, "source_system_id, event_label"
    )
    counts["domain_compatibility_requirements"] = _insert(
        conn,
        "domain_compatibility_requirements",
        [
            {
                "requirement_id": r["id"],
                "target_equipment_class_id": compatibility["target_equipment_class_id"],
                "category": r["category"],
                "requirement": r["requirement"],
                "target_value": r["target_value"],
                "rationale": r["rationale"],
            }
            for r in compatibility["requirements"]
        ],
        "requirement_id",
    )
    assessments = []
    for item in build_assessments():
        row = item.model_dump(mode="json")
        row["conditions"] = json.dumps(row["conditions"])
        assessments.append(row)
    counts["domain_compatibility_assessments"] = _insert(
        conn, "domain_compatibility_assessments", assessments, "assessment_id"
    )
    seed_facility(conn, root)
    counts["assets"] = scalar(conn, "SELECT count(*) FROM assets")
    counts["asset_relationships"] = scalar(conn, "SELECT count(*) FROM asset_relationships")
    return counts


def main() -> int:
    with connect() as conn:
        for table, count in seed(conn).items():
            print(f"seeded {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
