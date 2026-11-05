"""Canonical database behavior against PostgreSQL with PostGIS. CI data only."""

from __future__ import annotations

import pandas as pd
import psycopg
import pytest

from packages.domain import models
from packages.repositories.database import MIGRATIONS, MigrationError, migrate
from packages.repositories.lineage import (
    asset_exceptions,
    production_lineage,
    tag_semantics,
    telemetry_lineage,
)
from pipelines.normalize.load import load_all
from pipelines.normalize.schema_docs import render_schema_doc
from pipelines.normalize.seed import seed
from tests.conftest import CI_WORKSPACE, REPO_ROOT

pytestmark = pytest.mark.db
SPEC_TABLES = {
    "facilities", "assets", "source_systems", "ingestion_batches", "source_identifiers", "observations",
    "sensor_tags", "asset_observation_links", "asset_relationships", "production_records",
    "telemetry_events", "scenarios", "scenario_mappings", "inspection_observations", "anomaly_predictions",
    "work_orders", "approval_events", "audit_events",
}  # fmt: skip
GATE_2_TABLES = {
    "equipment_classes", "measurement_definitions", "equipment_measurement_capabilities",
    "sensor_tag_mappings", "data_quality_exceptions", "source_reconciliation_evidence",
}  # fmt: skip
OCD_BRONZE = CI_WORKSPACE / "data/bronze/nm_ocd/nm_ocd-fixture-20261105"


def scalar(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def test_migrations_build_a_fresh_database_with_every_required_table(fresh_database):
    with psycopg.connect(fresh_database) as conn:
        applied = migrate(conn)
        assert applied == sorted(p.name for p in MIGRATIONS.glob("*.sql"))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        }
        assert (SPEC_TABLES | GATE_2_TABLES) <= tables
        assert scalar(conn, "SELECT postgis_lib_version()").startswith("3.")
        assert scalar(conn, "SHOW server_version").startswith("16")


def test_migrating_twice_changes_nothing(fresh_database):
    with psycopg.connect(fresh_database) as conn:
        migrate(conn)
        assert migrate(conn) == []


def test_changed_migration_is_refused(fresh_database, tmp_path):
    first = tmp_path / "0001_a.sql"
    first.write_text("CREATE TABLE a (id int);")
    with psycopg.connect(fresh_database) as conn:
        migrate(conn, tmp_path)
        first.write_text("CREATE TABLE a (id bigint);")
        with pytest.raises(MigrationError):
            migrate(conn, tmp_path)


def test_failed_migration_rolls_back_completely(fresh_database, tmp_path):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id int); SELECT 1/0;")
    with psycopg.connect(fresh_database) as conn:
        with pytest.raises(psycopg.errors.DivisionByZero):
            migrate(conn, tmp_path)
        assert scalar(conn, "SELECT to_regclass('a') IS NULL")
        assert scalar(conn, "SELECT count(*) FROM schema_migrations") == 0


def test_seed_and_load_are_idempotent(fresh_database):
    with psycopg.connect(fresh_database) as conn:
        migrate(conn)
        first = seed(conn)
        assert seed(conn) == first
        load_all(conn, CI_WORKSPACE)
        before = scalar(conn, "SELECT count(*) FROM production_records")
        again = load_all(conn, CI_WORKSPACE)
        assert again["nm_ocd"]["already_loaded"] and again["petrobras_3w"]["already_loaded"]
        assert scalar(conn, "SELECT count(*) FROM production_records") == before


def test_geospatial_columns_and_indexes_exist(db):
    srid = scalar(db, "SELECT Find_SRID('public', 'source_assets', 'geometry')")
    assert srid == 4269
    indexes = {
        row[0]
        for row in db.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexdef ILIKE '%USING gist%'"
        )
    }
    for table in ("source_assets", "assets", "facilities", "observations"):
        assert any(f"public.{table} " in index and "geometry" in index for index in indexes), table


def test_canonical_counts_and_volumes_match_bronze(db):
    production = pd.read_parquet(OCD_BRONZE / "wcproduction.parquet")
    assert scalar(db, "SELECT count(*) FROM production_records") == len(production)
    expected = int(production["prod_amt"].dropna().astype(int).sum())
    assert scalar(db, "SELECT sum(reported_volume) FROM production_records") == expected


def test_wells_keep_every_source_field(db):
    wells = pd.read_parquet(OCD_BRONZE / "wells.parquet").set_index("id")
    row = db.execute(
        "SELECT attributes FROM source_assets WHERE source_asset_id = %s",
        (models.well_id("30-015-90001"),),
    ).fetchone()[0]
    source = wells.loc["30-015-90001"]
    assert row["ogrid_name"] == source["ogrid_name"]
    assert row["ulstr"] == source["ulstr"]
    assert set(row) == set(wells.columns) - {"provenance_class", "source_batch_id"} | {"id"}


def test_lineage_traces_production_to_raw_file_and_process(db):
    rows = production_lineage(db, "30-015-90001", "2026-06-01", "G")
    assert len(rows) == 2  # Two completions of one well, not summed or allocated.
    for row in rows:
        assert row["provenance_class"] == "OBSERVED"
        assert row["raw_file_path"].endswith("wcproduction.zip")
        assert len(row["raw_file_sha256"]) == 64
        assert row["transformation_id"] == "ocd.wcproduction.to_production_records@1"
        assert row["alters_values"] is False
    assert {r["reported_volume"] for r in rows} == {1000, 250}


def test_production_date_and_filing_like_date_stay_separate(db):
    row = db.execute(
        "SELECT reporting_period, source_effective_at FROM production_records LIMIT 1"
    ).fetchone()
    assert row[0].day == 1
    assert (row[1].year, row[1].month) != (row[0].year, row[0].month)


def test_null_volume_stays_null_and_missing_product_is_not_zero(db):
    assert scalar(db, "SELECT count(*) FROM production_records WHERE reported_volume IS NULL") == 1
    row = db.execute(
        """SELECT oil_volume_bbl, gas_volume_mcf_15025psia_60f FROM v_production_wide
           WHERE reporting_entity_id = %s""",
        (models.completion_id("30-015-90002", "97442"),),
    ).fetchone()
    assert row == (None, 0)


def test_gas_unit_carries_its_base_conditions(db):
    units = dict(db.execute("SELECT product_kind, unit_id FROM production_unit_rules").fetchall())
    assert units == {"G": "MCF_15025PSIA_60F", "O": "BBL_60F", "W": "BBL_60F"}
    conditions = scalar(
        db, "SELECT base_conditions FROM production_unit_rules WHERE product_kind='G'"
    )
    assert "15.025 psia" in conditions and "60 degrees F" in conditions


def test_bad_coordinate_is_quarantined_and_preserved(db):
    asset = models.well_id("30-015-90005")
    row = db.execute(
        "SELECT reported_latitude, geometry, spatial_status FROM source_assets WHERE source_asset_id=%s",
        (asset,),
    ).fetchone()
    assert row == (33.303, None, "QUARANTINED")
    assert (
        scalar(
            db,
            "SELECT count(*) FROM v_spatially_usable_source_assets WHERE source_asset_id=%s",
            asset,
        )
        == 0
    )
    found = asset_exceptions(db, asset)
    assert found[0]["exception_type"] == "COORDINATE_INCONSISTENT_WITH_PLSS"
    assert found[0]["original_values"]["latitude"] == "33.303"
    assert found[0]["evidence"]["distance_from_peer_median_km"] > 100
    assert found[0]["disposition"] == "QUARANTINED_FROM_SPATIAL"


def test_quarantined_coordinate_keeps_its_valid_production(db):
    assert production_lineage(db, "30-015-90005", "2026-06-01", "G")[0]["reported_volume"] == 750


def test_datum_conflicts_are_flagged_and_get_no_geometry(db):
    statuses = dict(
        db.execute(
            "SELECT external_identifier, spatial_status FROM source_assets WHERE external_identifier IN (%s,%s,%s)",
            ("30-015-90006", "30-015-90007", "30-015-90001"),
        ).fetchall()
    )
    assert statuses == {
        "30-015-90006": "UNRESOLVED_DATUM",
        "30-015-90007": "UNRESOLVED_DATUM",
        "30-015-90001": "USABLE",
    }
    types = {r["exception_type"] for r in asset_exceptions(db, models.well_id("30-015-90006"))}
    assert types == {"DATUM_LABEL_CONFLICT"}
    types = {r["exception_type"] for r in asset_exceptions(db, models.well_id("30-015-90007"))}
    assert types == {"DATUM_LABEL_MISSING"}


def test_acquisition_quarantine_is_visible_in_the_database(db):
    assert (
        scalar(
            db,
            "SELECT count(*) FROM data_quality_exceptions WHERE exception_type='ACQUISITION_INVALID_COORDINATES'",
        )
        == 1
    )


def test_ocd_channel_agreement_is_not_recorded_as_independent(db):
    assert (
        scalar(
            db, "SELECT count(*) FROM source_reconciliation_evidence WHERE channels_are_independent"
        )
        == 0
    )
    assert scalar(db, "SELECT count(*) FROM source_reconciliation_evidence") > 0
    assert (
        scalar(
            db,
            "SELECT count(*) FROM source_reconciliation_evidence WHERE field_name='datum_label' AND outcome='CONFLICT'",
        )
        == 1
    )


def test_telemetry_lineage_keeps_origin_and_source_well(db):
    real = telemetry_lineage(db, "petrobras_3w:2:WELL-00002_20131104004101")
    assert real["provenance_class"] == "OBSERVED"
    assert real["real_or_simulated_source"] == "REAL"
    assert real["source_asset_id"] == "petrobras_3w:well:WELL-00002"
    generated = telemetry_lineage(db, "petrobras_3w:2:SIMULATED_00001")
    assert generated["provenance_class"] == "SYNTHETIC"
    assert generated["source_asset_id"] is None


def test_every_sensor_has_the_nine_semantic_attributes(db):
    columns = (
        "original_source_tag, physical_quantity, equipment_location, measurement_reference_type, "
        "original_unit, canonical_unit, conversion_method, source_system, data_quality_state"
    )
    rows = db.execute(f"SELECT {columns} FROM v_tag_semantics").fetchall()
    assert len(rows) == 27 + 4  # 3W tags plus the synthetic AETHER sensors from Gate 3.
    assert all(value is not None for row in rows for value in row)


def test_all_3w_pressures_stay_unknown(db):
    pressure = db.execute(
        "SELECT DISTINCT measurement_reference_type, data_quality_state FROM v_tag_semantics WHERE physical_quantity='pressure' AND source_system='petrobras_3w'"
    ).fetchall()
    assert pressure == [("UNKNOWN", "SEMANTICS_INCOMPLETE")]
    row = tag_semantics(db, "PT-P")
    assert "Subsea" in row["equipment_location"]
    assert row["equipment_class_id"] == "OFFSHORE_SUBSEA_WELL"


def test_empty_sensor_is_recorded_as_empty_not_zero(db):
    row = db.execute(
        "SELECT quality_flag, value_count, numeric_value FROM observations WHERE metric_name='QBS' LIMIT 1"
    ).fetchone()
    assert row == ("EMPTY", 0, None)


def test_real_and_fictional_identities_never_overlap(db):
    overlap = scalar(
        db,
        "SELECT count(*) FROM assets a JOIN source_assets s ON a.asset_id = s.source_asset_id OR a.asset_id = s.external_identifier",
    )
    assert overlap == 0
    assert (
        scalar(
            db,
            "SELECT count(*) FROM assets WHERE NOT is_fictional OR provenance_class <> 'SYNTHETIC'",
        )
        == 0
    )
    assert scalar(db, "SELECT count(*) FROM assets WHERE asset_type='WELL'") == 12
    assert scalar(db, "SELECT count(*) FROM assets WHERE asset_type='COMPRESSOR'") == 4


@pytest.mark.parametrize(
    ("model", "table"),
    [
        (models.SourceAsset, "source_assets"),
        (models.HistoryRecord, "source_asset_history"),
        (models.ProductionRecord, "production_records"),
        (models.TelemetryEvent, "telemetry_events"),
        (models.Observation, "observations"),
        (models.SensorTag, "sensor_tags"),
        (models.MeasurementDefinition, "measurement_definitions"),
        (models.SensorTagMapping, "sensor_tag_mappings"),
        (models.CompatibilityAssessment, "domain_compatibility_assessments"),
        (models.ScenarioMapping, "scenario_mappings"),
        (models.DataQualityException, "data_quality_exceptions"),
        (models.ReconciliationEvidence, "source_reconciliation_evidence"),
    ],
)
def test_pydantic_contracts_match_database_columns(db, model, table):
    columns = {
        row[0]
        for row in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
            (table,),
        )
    }
    assert set(model.model_fields) <= columns


def test_schema_document_matches_the_implemented_schema(db):
    committed = (REPO_ROOT / "reports/data_quality/canonical_schema.md").read_text()
    assert render_schema_doc(db) == committed, "Run `make schema-docs` and commit the result."
