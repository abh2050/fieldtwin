"""Attempts to overstate aerial evidence or cross the real/fictional line. The database must refuse each.

One real Carbon Mapper plume from data/fixtures is inserted per test, inside a rolled-back transaction.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.db
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures"
OCD_WELL = "nm_ocd:well:30-015-90001"


def refused(conn, sql, params=None, error=psycopg.errors.IntegrityError):
    with pytest.raises(error):
        with conn.transaction():
            conn.execute(sql, params)


@pytest.fixture
def plumes(db) -> list[tuple[int, str]]:
    """Two real fixture plumes as observations: (observation_id, plume_id) pairs."""
    items = json.loads((FIXTURES / "carbon_mapper" / "plumes_page.json").read_text())["items"][1:3]
    db.execute(
        """INSERT INTO ingestion_batches (batch_id, source_system_id, source_version, ingestion_timestamp,
             original_checksum, source_record_count, accepted_count, rejected_count, processing_status, manifest_uri)
           VALUES ('cm-test', 'carbon_mapper', 'test', now(), %s, 2, 2, 0, 'COMPLETE', 'fixture')""",
        ("0" * 64,),
    )
    rows = []
    for item in items:
        lon, lat = item["geometry_json"]["coordinates"]
        observation_id = db.execute(
            """INSERT INTO observations (source_system_id, source_record_id, observed_at, observation_type, metric_name,
                 numeric_value, unit_id, quality_flag, geometry, provenance_class, original_record_uri, batch_id,
                 transformation_id)
               VALUES ('carbon_mapper', %s, %s, 'REMOTE_SENSING', 'ch4_plume_emission_rate', %s, 'kg_per_h',
                 'AS_PUBLISHED', ST_SetSRID(ST_MakePoint(%s, %s), 4326), 'OBSERVED', 'fixture', 'cm-test',
                 'carbon_mapper.plume.to_observation@1')
               RETURNING observation_id""",
            (item["plume_id"], item["scene_timestamp"][:19], item["emission_auto"], lon, lat),
        ).fetchone()[0]
        rows.append((observation_id, item["plume_id"]))
    return rows


@pytest.fixture
def plume(plumes) -> tuple[int, str]:
    return plumes[0]


def _review(
    db,
    review_id,
    evidence,
    evidence_id=None,
    supersedes=None,
    blind=True,
    features=(),
    kind="PLUME",
):
    """Insert a review of `evidence`, an (observation_id, source_record_id) pair."""
    observation_id, record_id = evidence
    db.execute(
        """INSERT INTO inspection_review_events (review_id, evidence_id, evidence_kind, observation_id, reviewer,
             outcome, visible_features, blinded_to_plume_status, supersedes, recorded_at, provenance_class)
           VALUES (%s, %s, %s, %s, 'reviewer-a', 'NO_FEATURE_OF_NOTE', %s, %s, %s, now(), 'OBSERVED')""",
        (
            review_id,
            evidence_id or record_id,
            kind,
            observation_id,
            list(features),
            blind,
            supersedes,
        ),
    )


def test_aerial_sources_are_seeded_with_their_terms(db):
    rows = dict(
        db.execute(
            "SELECT source_system_id, usage_constraints FROM source_systems WHERE source_system_id IN ('carbon_mapper', 'naip')"
        ).fetchall()
    )
    assert "Non-commercial" in rows["carbon_mapper"] and "no leak" in rows["naip"]


def test_proximity_can_never_be_verified_and_attribution_needs_verified_evidence(db, plume):
    refused(
        db,
        """INSERT INTO asset_observation_links (source_asset_id, observation_id, relationship_type, evidence_reference,
             verification_status, method_version, provenance_class)
           VALUES (%s, %s, 'EMISSION_NEAR', 'distance_m=10', 'VERIFIED', 'v1', 'DERIVED')""",
        (OCD_WELL, plume[0]),
    )
    refused(
        db,
        """INSERT INTO asset_observation_links (source_asset_id, observation_id, relationship_type,
             verification_status, method_version, provenance_class)
           VALUES (%s, %s, 'SOURCE_ATTRIBUTED_TO', 'UNVERIFIED', 'v1', 'DERIVED')""",
        (OCD_WELL, plume[0]),
    )


def test_a_plume_cannot_link_to_a_fictional_asset(db, plume):
    refused(
        db,
        """INSERT INTO asset_observation_links (asset_id, observation_id, relationship_type, verification_status,
             method_version, provenance_class)
           VALUES ('A-03', %s, 'EMISSION_NEAR', 'UNVERIFIED', 'v1', 'DERIVED')""",
        (plume[0],),
    )


def test_proximity_link_cannot_be_promoted_to_attribution(db, plume):
    link = db.execute(
        """INSERT INTO asset_observation_links (source_asset_id, observation_id, relationship_type, evidence_reference,
             verification_status, method_version, provenance_class)
           VALUES (%s, %s, 'EMISSION_NEAR', 'distance_m=10', 'UNVERIFIED', 'v1', 'DERIVED') RETURNING link_id""",
        (OCD_WELL, plume[0]),
    ).fetchone()[0]
    refused(
        db,
        "UPDATE asset_observation_links SET relationship_type = 'SOURCE_ATTRIBUTED_TO' WHERE link_id = %s",
        (link,),
        error=psycopg.errors.RestrictViolation,
    )


def test_reviews_are_append_only_and_supersede_within_one_item(db, plumes):
    plume, other = plumes
    _review(db, "r1", plume)
    refused(
        db,
        "UPDATE inspection_review_events SET outcome = 'IMAGE_UNUSABLE' WHERE review_id = 'r1'",
        error=psycopg.errors.RestrictViolation,
    )
    refused(
        db,
        "DELETE FROM inspection_review_events WHERE review_id = 'r1'",
        error=psycopg.errors.RestrictViolation,
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "r2", other, supersedes="r1")
    _review(db, "r3", plume, supersedes="r1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            _review(db, "r4", plume, supersedes="r1")


def test_review_outcomes_exclude_attribution(db, plume):
    refused(
        db,
        """INSERT INTO inspection_review_events (review_id, evidence_id, evidence_kind, observation_id, reviewer,
             outcome, blinded_to_plume_status, recorded_at, provenance_class)
           VALUES ('x', 'P1', 'PLUME', %s, 'reviewer-a', 'LEAK_CONFIRMED', true, now(), 'OBSERVED')""",
        (plume[0],),
    )


def test_an_unblinded_review_is_refused_even_from_the_application_role(db, plume):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "u1", plume, blind=False)
    db.execute("SET LOCAL ROLE fieldtwin_app")
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "u2", plume, blind=False)
    _review(db, "u3", plume, features=("TANK_BATTERY",))


def test_reviews_hold_only_vocabulary_values(db, plume):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "v1", plume, features=("This well released methane",))
    columns = {
        r[0]
        for r in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'inspection_review_events'"
        ).fetchall()
    }
    assert not {"note", "comment", "finding", "text"} & columns


def test_review_identifier_must_name_its_observation(db, plumes):
    plume, other = plumes
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "i1", plume, evidence_id=other[1])
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "i2", plume, evidence_id="P1")


def test_review_kind_must_match_the_observation_source(db, plume):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "k1", plume, kind="NAIP_CHIP")


def test_visible_features_are_distinct_in_the_database(db, plume):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "d1", plume, features=("WELL_PAD", "WELL_PAD"))


def test_a_correct_review_is_accepted_from_the_application_role(db, plume):
    db.execute("SET LOCAL ROLE fieldtwin_app")
    _review(db, "ok", plume, features=("WELL_PAD", "TANK_BATTERY"))
    row = db.execute(
        "SELECT evidence_id, evidence_kind FROM inspection_review_events WHERE review_id = 'ok'"
    ).fetchone()
    assert row == (plume[1], "PLUME")


def test_reviews_cover_aerial_evidence_only(db):
    other = db.execute(
        "SELECT observation_id FROM observations WHERE source_system_id = 'petrobras_3w' LIMIT 1"
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            _review(db, "r9", (other, "x"))


def _event(db):
    return db.execute(
        "SELECT event_id, scenario_id, scenario_run_id, target_asset_id, affected_asset_id FROM shared_events "
        "WHERE domain = 'AETHER_SYNTHETIC' LIMIT 1"
    ).fetchone()


def _request(db, asset, event_id, scenario_id, run_id, affected="GS-A"):
    db.execute(
        """INSERT INTO inspection_requests (request_id, asset_id, affected_asset_id, scenario_id, scenario_run_id,
             trigger_event_id, inspection_type, reason, status, created_at, provenance_class)
           VALUES ('INSP-test', %s, %s, %s, %s, %s, 'GROUND_INSPECTION', 'test', 'REQUESTED', now(), 'SYNTHETIC')""",
        (asset, affected, scenario_id, run_id, event_id),
    )


def test_requests_target_fictional_assets_from_synthetic_events_only(db):
    from pipelines.reconcile.run import load_rules
    from pipelines.synthetic.aether_field import execute_all, persist_all

    # Record the simulated field runs in this rolled-back transaction, so a real synthetic event exists.
    persist_all(db, execute_all(), {}, load_rules()["algorithms"]["scenario"])
    event = _event(db)
    event_id, scenario_id, run_id, target, affected = event
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db.transaction():
            _request(db, OCD_WELL, event_id, scenario_id, run_id)
    benchmark = db.execute(
        "SELECT event_id FROM shared_events WHERE domain = 'OFFSHORE_BENCHMARK' LIMIT 1"
    ).fetchone()
    if benchmark:
        with pytest.raises(psycopg.errors.CheckViolation):
            with db.transaction():
                _request(db, target, benchmark[0], scenario_id, run_id, affected)
    _request(db, target, event_id, scenario_id, run_id, affected)
    refused(db, "UPDATE inspection_requests SET provenance_class = 'OBSERVED'")
