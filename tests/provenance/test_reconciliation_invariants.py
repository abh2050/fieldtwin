"""Attempts to break the Gate 3 boundaries directly in the database. Each must be refused."""

from __future__ import annotations

import json

import psycopg
import pytest

pytestmark = pytest.mark.db
REAL_EVENT = "petrobras_3w:2:WELL-00002_20131104004101"
REAL_INSTANCE = "WELL-00002_20131104004101"
OCD_WELL = "nm_ocd:well:30-015-90001"
DEFAULTS = {
    "module": "IDENTITY",
    "subject_type": "SOURCE_ASSET",
    "subject_id": OCD_WELL,
    "object_type": "SOURCE_RECORD",
    "object_id": "record",
    "relationship_type": "SAME_AS",
    "method": "AUTHORITATIVE_IDENTIFIER",
    "evidence": json.dumps({"reason": "test"}),
    "verification_status": "VERIFIED",
    "provenance_class": "DERIVED",
    "algorithm_version": "test@1",
}


def insert_decision(conn, **overrides):
    row = {**DEFAULTS, **overrides}
    columns = ", ".join(row)
    marks = ", ".join(["%s"] * len(row))
    return conn.execute(
        f"INSERT INTO reconciliation_decisions ({columns}) VALUES ({marks}) RETURNING decision_id",
        tuple(row.values()),
    ).fetchone()[0]


def refused(conn, error=psycopg.errors.CheckViolation, **overrides):
    with pytest.raises(error):
        with conn.transaction():
            insert_decision(conn, **overrides)


def test_valid_decision_is_accepted(db):
    assert insert_decision(db) > 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"object_type": "ASSET", "object_id": "A-03"},
        {"subject_type": "ASSET", "subject_id": "A-03", "object_type": "SOURCE_ASSET"},
        {"subject_type": "ASSET", "subject_id": "A-03"},
        {"method": "NAME_SIMILARITY"},
        {"method": "GEOSPATIAL_PROXIMITY"},
        {"method": "UNIT_SIMILARITY"},
        {"method": "NAME_SIMILARITY", "verification_status": "UNVERIFIED"},
        {"provenance_class": "INFERRED"},
        {"evidence": "{}"},
        {"evidence": "[1]"},
        {"object_id": None},
        {"algorithm_version": "unversioned"},
        {"confidence": 1.5},
        {
            "relationship_type": "PROXIMITY_CANDIDATE",
            "method": "GEOSPATIAL_PROXIMITY",
            "provenance_class": "INFERRED",
        },
        {
            "relationship_type": "EMISSION_NEAR",
            "method": "GEOSPATIAL_PROXIMITY",
            "provenance_class": "INFERRED",
        },
        {
            "relationship_type": "PROXIMITY_CANDIDATE",
            "method": "GEOSPATIAL_PROXIMITY",
            "verification_status": "UNVERIFIED",
        },
        {"relationship_type": "COMPLETION_OF", "method": "NAME_SIMILARITY"},
        {"relationship_type": "SAME_MEASUREMENT", "method": "UNIT_SIMILARITY"},
        {"method": "HUMAN_REVIEW"},
    ],
)
def test_invalid_decisions_are_refused_by_the_database(db, overrides):
    refused(db, **overrides)


def experimental(**overrides):
    return {
        "module": "SCENARIO",
        "subject_type": "SCENARIO_RUN",
        "subject_id": "run",
        "object_type": "ASSET",
        "object_id": "A-03",
        "relationship_type": "EXPERIMENTAL_ASSIGNMENT",
        "method": "DECLARED_BY_SCENARIO_CONFIG",
        "verification_status": "UNVERIFIED",
        "provenance_class": "SYNTHETIC",
        **overrides,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"verification_status": "VERIFIED"},
        {"provenance_class": "OBSERVED"},
        {"provenance_class": "DERIVED"},
        {"object_type": "SOURCE_ASSET", "object_id": OCD_WELL},
    ],
)
def test_experimental_assignment_cannot_become_authoritative(db, overrides):
    refused(db, **experimental(**overrides))


def test_decisions_are_append_only(db):
    decision = insert_decision(db)
    for sql in (
        "UPDATE reconciliation_decisions SET verification_status = 'REJECTED' WHERE decision_id = %s",
        "DELETE FROM reconciliation_decisions WHERE decision_id = %s",
    ):
        with pytest.raises(psycopg.errors.RestrictViolation):
            with db.transaction():
                db.execute(sql, (decision,))


def test_unknown_relationship_needs_no_fabricated_confidence(db):
    decision = insert_decision(
        db,
        method="NO_SHARED_IDENTIFIER",
        verification_status="UNRESOLVED",
    )
    row = db.execute(
        "SELECT confidence FROM reconciliation_decisions WHERE decision_id = %s", (decision,)
    ).fetchone()
    assert row[0] is None


# Scenario runs


def run_values(**overrides):
    values = {
        "scenario_run_id": "run",
        "scenario_id": "S1",
        "case_name": "fault",
        "target_asset_id": "A-03",
        "affected_asset_id": "GS-A",
        "simulator_name": "sim",
        "simulator_version": 1,
        "config_sha256": "a" * 64,
        "output_sha256": "b" * 64,
        "output_uri": "u",
        "random_seed": 1,
        "sample_count": 1,
        "sampling_interval_s": 60,
        "fault_onset_offset_s": 10,
        "parameters": "{}",
        "invariants": "[]",
        "provenance_class": "SYNTHETIC",
        "transformation_id": "aether.simulator.to_run@1",
        **overrides,
    }
    return values


def insert_run(conn, **overrides):
    conn.execute(
        """INSERT INTO scenarios (scenario_id, scenario_name, scenario_description, target_facility_id, scenario_version, random_seed)
           VALUES ('S1', 'test', 'test', 'AETHER-FIELD', 1, 7) ON CONFLICT DO NOTHING"""
    )
    values = run_values(**overrides)
    columns = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    conn.execute(f"INSERT INTO scenario_runs ({columns}) VALUES ({marks})", tuple(values.values()))


def test_run_cannot_target_a_real_well(db):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db.transaction():
            insert_run(db, target_asset_id=OCD_WELL)


@pytest.mark.parametrize(
    "overrides",
    [
        {"provenance_class": "OBSERVED"},
        {"fault_onset_offset_s": None},
        {"case_name": "nominal"},
        {"case_name": "other", "fault_onset_offset_s": None},
    ],
)
def test_invalid_runs_are_refused(db, overrides):
    with pytest.raises(psycopg.errors.IntegrityError):
        with db.transaction():
            insert_run(db, **overrides)


def test_runs_are_immutable(db):
    insert_run(db)
    with pytest.raises(psycopg.errors.RestrictViolation):
        with db.transaction():
            db.execute("UPDATE scenario_runs SET random_seed = 2")


def test_simulated_series_cannot_claim_observed(db):
    insert_run(db)
    with pytest.raises(psycopg.errors.IntegrityError):
        with db.transaction():
            db.execute(
                """INSERT INTO observations (source_system_id, source_record_id, observation_type, metric_name,
                     quality_flag, provenance_class, original_record_uri, scenario_id, scenario_run_id, batch_id,
                     transformation_id)
                   SELECT 'aether_synthetic', 'x', 'TELEMETRY_SERIES', 'm', 'COMPLETE', 'OBSERVED', 'u', 'S1', 'run',
                     batch_id, '3w.real_series.to_observation@1' FROM ingestion_batches LIMIT 1"""
            )


# Domain boundary


def mapping(conn, assessment):
    conn.execute(
        """INSERT INTO scenarios (scenario_id, scenario_name, scenario_description, target_facility_id, scenario_version, random_seed)
           VALUES ('S1', 'test', 'test', 'AETHER-FIELD', 1, 7) ON CONFLICT DO NOTHING"""
    )
    conn.execute(
        "UPDATE telemetry_events SET source_event_label = 6, source_event_class = 'QUICK_RESTRICTION_IN_PCK' WHERE event_id = %s",
        (REAL_EVENT,),
    )
    conn.execute(
        """INSERT INTO scenario_mappings (scenario_id, target_asset_id, telemetry_event_id, original_source_instance_id,
             transformation_config, compatibility_assessment_id, conditions_satisfied, mapping_provenance)
           VALUES ('S1', 'A-03', %s, %s, '{}', %s, '["a", "b", "c", "d"]', 'REPLAYED')""",
        (REAL_EVENT, REAL_INSTANCE, assessment),
    )


def test_conditionally_compatible_3w_event_is_still_refused_by_the_boundary(db):
    """The assessment layer would allow this with evidence, and the domain boundary refuses it."""
    with pytest.raises(psycopg.errors.CheckViolation, match="domain boundary"):
        with db.transaction():
            mapping(db, "3w-aether:EVENT_CLASS:QUICK_RESTRICTION_IN_PCK:v1")


def test_boundary_defaults_to_refusal_when_no_rule_exists(db):
    db.execute("DELETE FROM domain_boundaries")
    with pytest.raises(psycopg.errors.CheckViolation, match="domain boundary"):
        with db.transaction():
            mapping(db, "3w-aether:EVENT_CLASS:QUICK_RESTRICTION_IN_PCK:v1")


# Equipment relationships


@pytest.mark.parametrize(
    ("source", "target"),
    [("C-01", "A-03"), ("A-03", "C-01"), ("GS-A", "A-03"), ("A-03", "A-04"), ("IV-A", "GS-A")],
)
def test_invalid_equipment_relationships_are_refused(db, source, target):
    with pytest.raises(psycopg.errors.CheckViolation, match="invalid equipment relationship"):
        with db.transaction():
            db.execute(
                """INSERT INTO asset_relationships (source_asset_id, target_asset_id, relationship_type, evidence_type, provenance_class)
                   VALUES (%s, %s, 'FEEDS', 'TEST', 'SYNTHETIC')""",
                (source, target),
            )


def test_declared_flow_path_is_stored_as_synthetic(db):
    rows = db.execute(
        """SELECT source_asset_id, target_asset_id, provenance_class FROM asset_relationships
           WHERE source_asset_id IN ('A-03', 'GS-A', 'GS-TRUNK') ORDER BY 1"""
    ).fetchall()
    assert rows == [
        ("A-03", "GS-A", "SYNTHETIC"),
        ("GS-A", "GS-TRUNK", "SYNTHETIC"),
        ("GS-TRUNK", "COMP-STATION", "SYNTHETIC"),
    ]


# Shared events


def event_values(**overrides):
    return {
        "event_id": "e",
        "schema_version": 1,
        "domain": "OFFSHORE_BENCHMARK",
        "event_kind": "SOURCE_LABEL",
        "event_class": "C",
        "source_system_id": "petrobras_3w",
        "telemetry_event_id": REAL_EVENT,
        "evidence": json.dumps({"k": "v"}),
        "provenance_class": "DERIVED",
        "transformation_id": "3w.benchmark_event_adapter.real@1",
        **overrides,
    }


def insert_event(conn, **overrides):
    values = event_values(**overrides)
    columns = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    conn.execute(f"INSERT INTO shared_events ({columns}) VALUES ({marks})", tuple(values.values()))


def test_benchmark_event_is_accepted_with_source_identity(db):
    insert_event(db)


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_asset_id": "A-03"},
        {"affected_asset_id": "GS-A"},
        {"telemetry_event_id": None},
        {"source_system_id": "aether_synthetic"},
        {"event_kind": "KNOWN_SYNTHETIC_ONSET"},
        {"provenance_class": "OBSERVED", "transformation_id": "3w.real_instance.to_event@1"},
        {"evidence": "{}"},
    ],
)
def test_benchmark_event_cannot_reach_aether(db, overrides):
    with pytest.raises(psycopg.errors.IntegrityError):
        with db.transaction():
            insert_event(db, **overrides)


def test_real_instance_event_cannot_be_labeled_synthetic(db):
    with pytest.raises(psycopg.errors.CheckViolation, match="benchmark event"):
        with db.transaction():
            insert_event(
                db,
                provenance_class="SYNTHETIC",
                transformation_id="3w.benchmark_event_adapter.generated@1",
            )


def test_generated_instance_event_cannot_be_labeled_derived(db):
    with pytest.raises(psycopg.errors.CheckViolation, match="benchmark event"):
        with db.transaction():
            insert_event(db, telemetry_event_id="petrobras_3w:2:SIMULATED_00001")


def test_aether_event_needs_its_scenario_and_stays_synthetic(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            insert_event(
                db,
                domain="AETHER_SYNTHETIC",
                event_kind="KNOWN_SYNTHETIC_ONSET",
                source_system_id="aether_synthetic",
                telemetry_event_id=None,
                provenance_class="SYNTHETIC",
                transformation_id="aether.simulator.to_event@1",
                target_asset_id="A-03",
            )
