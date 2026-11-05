"""Check the real canonical database against bronze. Exits 1 if any check fails."""

from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd
import psycopg
import yaml

from packages.repositories.database import REPO_ROOT, connect
from pipelines.acquire.common.core import utc_now
from pipelines.profile.common import FAIL, PASS, Check, latest_complete

OUTPUT = REPO_ROOT / "reports" / "data_quality" / "canonical_validation.json"


def _value(conn: psycopg.Connection, sql: str, *params: object) -> int:
    row = conn.execute(sql, params).fetchone()
    return 0 if row is None or row[0] is None else int(row[0])


def _equal(name: str, actual: int, expected: int, rule: str) -> Check:
    return Check(name, PASS if actual == expected else FAIL, f"{actual} vs {expected}", rule)


def _zero(name: str, actual: int, rule: str) -> Check:
    return Check(name, PASS if actual == 0 else FAIL, actual, rule)


def run_checks(conn: psycopg.Connection) -> list[Check]:
    root = REPO_ROOT
    ocd = latest_complete(root, "nm_ocd")
    w3 = latest_complete(root, "petrobras_3w")
    bronze = root / "data" / "bronze" / "nm_ocd" / ocd["batch_id"]
    wells = pd.read_parquet(bronze / "wells.parquet")
    history = pd.read_parquet(bronze / "wellhistory.parquet")
    production = pd.read_parquet(bronze / "wcproduction.parquet")
    instances = pd.read_parquet(
        root / "data" / "bronze" / "petrobras_3w" / w3["batch_id"] / "instances.parquet"
    )
    box = yaml.safe_load((root / "config" / "sources" / "nm_ocd.yaml").read_text())["bounds"][
        "eddy_county_approx"
    ]

    checks = [
        _equal(
            "wells_match_bronze",
            _value(
                conn,
                "SELECT count(*) FROM source_assets WHERE source_system_id='nm_ocd' AND asset_type='WELL'",
            ),
            len(wells),
            "Every accepted well is loaded",
        ),
        _equal(
            "history_matches_bronze",
            _value(conn, "SELECT count(*) FROM source_asset_history"),
            len(history),
            "Every accepted history row is loaded",
        ),
        _equal(
            "production_matches_bronze",
            _value(conn, "SELECT count(*) FROM production_records"),
            len(production),
            "Every accepted production row is loaded",
        ),
        _equal(
            "completions_match_bronze",
            _value(conn, "SELECT count(*) FROM source_assets WHERE asset_type='WELL_COMPLETION'"),
            len(production[["api", "pool_idn"]].drop_duplicates()),
            "One completion per API and pool",
        ),
        _equal(
            "instances_match_bronze",
            _value(conn, "SELECT count(*) FROM telemetry_events"),
            len(instances),
            "Every 3W instance is loaded",
        ),
    ]
    for kind in ("G", "O", "W"):
        rows = production[production["prd_knd_cde"].str.strip() == kind]
        checks.append(
            _equal(
                f"volume_total_{kind}_matches_bronze",
                _value(
                    conn,
                    "SELECT sum(reported_volume) FROM production_records WHERE product_kind=%s",
                    kind,
                ),
                int(rows["prod_amt"].dropna().astype(int).sum()),
                "Volumes are not altered by loading",
            )
        )
    checks += [
        _zero(
            "usable_wells_outside_county_box",
            _value(
                conn,
                """SELECT count(*) FROM v_spatially_usable_source_assets
                   WHERE source_system_id='nm_ocd' AND NOT (
                     ST_Y(geometry) BETWEEN %s AND %s AND ST_X(geometry) BETWEEN %s AND %s)""",
                box["lat_min"],
                box["lat_max"],
                box["lon_min"],
                box["lon_max"],
            ),
            "Zero tolerance in the spatial analytics population",
        ),
        _zero(
            "non_usable_assets_with_geometry",
            _value(
                conn,
                "SELECT count(*) FROM source_assets WHERE spatial_status <> 'USABLE' AND geometry IS NOT NULL",
            ),
            "Quarantined and unresolved wells have no analytic geometry",
        ),
        _zero(
            "quarantined_without_exception",
            _value(
                conn,
                """SELECT count(*) FROM source_assets a WHERE a.spatial_status IN ('QUARANTINED','UNRESOLVED_DATUM')
                   AND NOT EXISTS (SELECT 1 FROM data_quality_exceptions e WHERE e.source_asset_id = a.source_asset_id)""",
            ),
            "Every spatial exclusion has a recorded reason",
        ),
        _zero(
            "quarantined_without_reported_coordinates",
            _value(
                conn,
                """SELECT count(*) FROM source_assets WHERE spatial_status='QUARANTINED'
                   AND (reported_latitude IS NULL OR reported_longitude IS NULL)""",
            ),
            "Original coordinates are preserved",
        ),
        _equal(
            "production_lineage_complete",
            _value(conn, "SELECT count(*) FROM v_production_lineage"),
            _value(conn, "SELECT count(*) FROM production_records"),
            "Each row traces to a raw file, process, and batch",
        ),
        _equal(
            "telemetry_lineage_complete",
            _value(conn, "SELECT count(*) FROM v_telemetry_lineage"),
            _value(conn, "SELECT count(*) FROM telemetry_events"),
            "Each instance traces to a raw file, process, and batch",
        ),
        _zero(
            "ocd_channels_marked_independent",
            _value(
                conn,
                "SELECT count(*) FROM source_reconciliation_evidence WHERE channels_are_independent",
            ),
            "OCD channel agreement is not independent confirmation",
        ),
        _zero(
            "scenario_mappings_present",
            _value(conn, "SELECT count(*) FROM scenario_mappings"),
            "No source telemetry is mapped into a scenario",
        ),
        _zero(
            "real_observations_linked_to_fictional_assets",
            _value(
                conn,
                """SELECT count(*) FROM asset_observation_links l JOIN observations o USING (observation_id)
                   WHERE l.asset_id IS NOT NULL AND o.source_system_id <> 'aether_synthetic'""",
            ),
            "Only synthetic observations can be linked to AETHER assets",
        ),
        _zero(
            "non_synthetic_fictional_assets",
            _value(
                conn,
                "SELECT count(*) FROM assets WHERE provenance_class <> 'SYNTHETIC' OR NOT is_fictional",
            ),
            "Fictional assets are always SYNTHETIC",
        ),
        _zero(
            "generated_instances_marked_observed",
            _value(
                conn,
                "SELECT count(*) FROM telemetry_events WHERE real_or_simulated_source <> 'REAL' AND provenance_class = 'OBSERVED'",
            ),
            "Generated 3W instances are never OBSERVED",
        ),
        _zero(
            "pressure_tags_with_assumed_reference",
            _value(
                conn,
                "SELECT count(*) FROM sensor_tags WHERE source_system_id='petrobras_3w' AND physical_quantity='pressure' AND pressure_reference_type <> 'UNKNOWN'",
            ),
            "3W pressure references stay UNKNOWN",
        ),
        _zero(
            "cross_domain_tag_mappings",
            _value(
                conn,
                """SELECT count(*) FROM sensor_tag_mappings m
                   JOIN measurement_definitions d USING (measurement_definition_id)
                   JOIN sensor_tags t USING (tag_id)
                   WHERE d.equipment_class_id <> t.equipment_class_id""",
            ),
            "No sensor maps across equipment classes",
        ),
    ]
    return checks


def main() -> int:
    with connect() as conn:
        checks = run_checks(conn)
    failed = [c.name for c in checks if c.status == FAIL]
    report = {
        "validated_at": utc_now(),
        "passed": not failed,
        "failed": failed,
        "checks": [asdict(c) for c in checks],
    }
    OUTPUT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    for check in checks:
        print(f"{check.status} {check.name}: {check.measured}")
    print(f"checks={len(checks)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
