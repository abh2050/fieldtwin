"""Checks on the real canonical database. Needs `make db-load` on the batches from `make acquire`."""

from __future__ import annotations

import pandas as pd
import pytest

from packages.repositories.database import connect
from packages.repositories.lineage import asset_exceptions, production_lineage
from pipelines.normalize.reports import render_compatibility_report
from pipelines.normalize.validate_canonical import run_checks
from pipelines.profile.common import FAIL, latest_complete
from tests.conftest import REPO_ROOT

pytestmark = [pytest.mark.db, pytest.mark.acquired]


@pytest.fixture
def real():
    with connect() as conn:
        yield conn


def value(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def test_all_canonical_validation_checks_pass(real):
    assert [c.name for c in run_checks(real) if c.status == FAIL] == []


def test_data_driven_rule_quarantines_exactly_one_coordinate(real):
    rows = real.execute(
        "SELECT source_asset_id, reported_latitude, geometry FROM source_assets WHERE spatial_status='QUARANTINED'"
    ).fetchall()
    assert len(rows) == 1
    asset, latitude, geometry = rows[0]
    assert latitude is not None and geometry is None  # The reported value is kept locally.
    found = asset_exceptions(real, asset)
    assert found[0]["evidence"]["same_value_in_arcgis_and_ftp"] is True
    assert found[0]["evidence"]["inside_county_box"] is False
    assert found[0]["evidence"]["distance_from_peer_median_km"] > 100
    assert found[0]["status"] == "OPEN"


def test_unresolved_datums_are_all_flagged(real):
    assert (
        value(real, "SELECT count(*) FROM source_assets WHERE spatial_status='UNRESOLVED_DATUM'")
        == 35
    )
    assert (
        value(
            real,
            "SELECT count(*) FROM data_quality_exceptions WHERE exception_type='DATUM_LABEL_CONFLICT'",
        )
        == 30
    )
    assert (
        value(
            real,
            "SELECT count(*) FROM data_quality_exceptions WHERE exception_type='DATUM_LABEL_MISSING'",
        )
        == 5
    )


def test_spatial_population_adds_up(real):
    usable = value(real, "SELECT count(*) FROM v_spatially_usable_source_assets")
    assert usable + 1 + 35 == value(
        real,
        "SELECT count(*) FROM source_assets WHERE source_system_id='nm_ocd' AND asset_type='WELL'",
    )


def test_quarantined_rows_from_acquisition_are_all_visible(real):
    manifest = latest_complete(REPO_ROOT, "nm_ocd")
    count = value(
        real,
        "SELECT count(*) FROM data_quality_exceptions WHERE exception_type LIKE 'ACQUISITION_%%'",
    )
    assert count == manifest["rejected_count"]


def test_real_production_value_traces_back_to_bronze_and_raw(real):
    manifest = latest_complete(REPO_ROOT, "nm_ocd")
    bronze = pd.read_parquet(
        REPO_ROOT / "data/bronze/nm_ocd" / manifest["batch_id"] / "wcproduction.parquet"
    )
    sample = bronze[bronze["prd_knd_cde"].str.strip() == "G"].iloc[100]
    period = f"{int(sample['prodn_yr'])}-{int(sample['prodn_mth']):02d}-01"
    rows = production_lineage(real, sample["api"], period, "G")
    match = next(r for r in rows if r["reporting_entity_id"].endswith(sample["pool_idn"]))
    assert match["reported_volume"] == int(sample["prod_amt"])
    assert match["unit_id"] == "MCF_15025PSIA_60F"
    zip_entry = next(f for f in manifest["files"] if f["path"].endswith("wcproduction.zip"))
    assert match["raw_file_sha256"] == zip_entry["sha256"]


def test_3w_instance_ids_repeat_across_classes_without_collision(real):
    repeats = value(
        real,
        "SELECT count(*) FROM (SELECT source_instance_id FROM telemetry_events GROUP BY 1 HAVING count(*) > 1) r",
    )
    assert repeats > 0
    assert value(real, "SELECT count(*) FROM telemetry_events") == 498


def test_observations_describe_every_sensor_in_every_instance(real):
    assert (
        value(real, "SELECT count(*) FROM observations WHERE source_system_id = 'petrobras_3w'")
        == 498 * 27
    )
    assert (
        value(real, "SELECT count(*) FROM observations WHERE source_system_id = 'aether_synthetic'")
        == 2 * 4 + 6 * 39
    )
    assert (
        value(
            real,
            "SELECT count(*) FROM observations WHERE quality_flag='EMPTY' AND value_count <> 0",
        )
        == 0
    )


def test_compatibility_report_matches_the_contract():
    committed = (REPO_ROOT / "reports/reconciliation/semantic_compatibility.md").read_text()
    assert committed == render_compatibility_report()


def test_all_real_wells_are_verified_by_identifier(real):
    row = real.execute(
        """SELECT count(*) FROM reconciliation_decisions WHERE relationship_type = 'SAME_AS'
           AND verification_status = 'VERIFIED' AND method = 'AUTHORITATIVE_IDENTIFIER'"""
    ).fetchone()
    assert row[0] == value(
        real,
        "SELECT count(*) FROM source_assets WHERE source_system_id='nm_ocd' AND asset_type='WELL'",
    )


def test_wells_at_identical_coordinates_keep_separate_identities(real):
    """Real pairs at zero distance exist. They stay candidates and stay distinct wells."""
    pairs = real.execute(
        """SELECT subject_id, object_id, verification_status FROM reconciliation_decisions
           WHERE relationship_type = 'PROXIMITY_CANDIDATE' AND (evidence->>'distance_m')::float = 0"""
    ).fetchall()
    assert pairs
    for subject, other, status in pairs:
        assert subject != other and status == "UNVERIFIED"
        same = real.execute(
            """SELECT count(*) FROM reconciliation_decisions WHERE relationship_type = 'SAME_AS'
               AND verification_status = 'VERIFIED' AND subject_id = %s AND object_id = %s""",
            (subject, other),
        ).fetchone()[0]
        assert same == 0


def test_provenance_audit_is_clean_on_real_data(real):
    from packages.reconciliation.provenance import audit_provenance

    assert [f.name for f in audit_provenance(real) if f.violations] == []


def test_3w_events_preserve_every_instance_without_aether_scope(real):
    assert (
        value(real, "SELECT count(*) FROM shared_events WHERE domain='OFFSHORE_BENCHMARK'") == 498
    )
    assert (
        value(
            real,
            "SELECT count(*) FROM shared_events WHERE domain='OFFSHORE_BENCHMARK' AND (target_asset_id IS NOT NULL OR scenario_id IS NOT NULL)",
        )
        == 0
    )


def test_unlabelled_benchmark_instances_are_all_flagged(real):
    expected = value(
        real,
        "SELECT count(*) FROM shared_events WHERE domain='OFFSHORE_BENCHMARK' AND onset_offset_s IS NULL AND event_class <> 'NORMAL'",
    )
    assert expected > 0
    assert expected == value(
        real,
        "SELECT count(*) FROM data_quality_exceptions WHERE exception_type='BENCHMARK_INSTANCE_WITHOUT_EVENT_LABEL'",
    )


def test_every_synthetic_observation_on_real_database_has_a_complete_chain(real):
    row = real.execute(
        "SELECT count(*), count(*) FILTER (WHERE chain_complete) FROM v_synthetic_provenance_chain"
    ).fetchone()
    assert row == (242, 242)
