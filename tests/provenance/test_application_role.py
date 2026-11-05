"""Attempt to bypass the boundary as the application role, and to break the provenance chain."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from packages.reconciliation.provenance import audit_provenance
from packages.scenario_engine.config import load_config
from pipelines.reconcile.run import load_rules
from pipelines.synthetic.aether_fault_001 import execute, persist

pytestmark = pytest.mark.db
REAL_EVENT = "petrobras_3w:2:WELL-00002_20131104004101"
REAL_INSTANCE = "WELL-00002_20131104004101"
URIS = {"nominal": "data/gold/nominal.parquet", "fault": "data/gold/fault.parquet"}
DENIED = psycopg.errors.InsufficientPrivilege


@pytest.fixture
def app(db):
    """The same connection, acting as the application role for the rest of the test."""
    db.execute("SET LOCAL ROLE fieldtwin_app")
    return db


def denied(conn, sql, params=None):
    with pytest.raises(DENIED):
        with conn.transaction():
            conn.execute(sql, params)


def test_role_has_no_elevated_attributes(db):
    row = db.execute(
        """SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin
           FROM pg_roles WHERE rolname = 'fieldtwin_app'"""
    ).fetchone()
    assert row == (False, False, False, False, False, False)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE domain_boundaries SET is_allowed = true",
        "DELETE FROM domain_boundaries",
        "INSERT INTO domain_boundaries VALUES ('petrobras_3w', 'REAL_ONSHORE', true, 'x')",
        "TRUNCATE domain_boundaries",
        "UPDATE domain_compatibility_assessments SET classification = 'DIRECTLY_COMPATIBLE'",
        "INSERT INTO equipment_relationship_rules VALUES ('COMPRESSOR', 'FEEDS', 'WELL', 'x')",
        "UPDATE transformations SET alters_values = false",
        "ALTER TABLE scenario_mappings DISABLE TRIGGER scenario_mapping_zz_boundary",
        "ALTER TABLE scenario_mappings DISABLE TRIGGER ALL",
        "DROP TRIGGER scenario_mapping_zz_boundary ON scenario_mappings",
        "DROP TABLE domain_boundaries",
        "CREATE TABLE sneaky (id int)",
        "CREATE OR REPLACE FUNCTION enforce_domain_boundary() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$",
        "UPDATE sensor_tags SET pressure_reference_type = 'GAUGE'",
        "UPDATE production_records SET reported_volume = 1",
        "DELETE FROM source_assets",
        "UPDATE assets SET is_fictional = false",
    ],
)
def test_application_cannot_weaken_boundaries_or_change_source_data(app, sql):
    denied(app, sql)


def test_application_cannot_enter_replica_mode_to_skip_triggers(app):
    denied(app, "SET LOCAL session_replication_role = replica")


@pytest.fixture
def real_login(canonical_database):
    """A genuine login connection, like an application's. SET ROLE from a superuser session isn't."""
    name = f"ft_login_{uuid.uuid4().hex[:10]}"
    password = uuid.uuid4().hex
    with psycopg.connect(canonical_database, autocommit=True) as admin:
        admin.execute(f"CREATE ROLE {name} LOGIN PASSWORD '{password}' IN ROLE fieldtwin_app")
    parts = {**conninfo_to_dict(canonical_database), "user": name, "password": password}
    try:
        with psycopg.connect(make_conninfo(**parts)) as conn:
            yield conn
            conn.rollback()
    finally:
        with psycopg.connect(canonical_database, autocommit=True) as admin:
            admin.execute(f"DROP OWNED BY {name}")
            admin.execute(f"DROP ROLE {name}")


@pytest.mark.parametrize(
    "sql",
    [
        "SET ROLE fieldtwin",
        "SET SESSION AUTHORIZATION fieldtwin",
        "SET session_replication_role = replica",
        "UPDATE domain_boundaries SET is_allowed = true",
        "ALTER TABLE scenario_mappings DISABLE TRIGGER ALL",
        "DROP TRIGGER scenario_mapping_zz_boundary ON scenario_mappings",
        "CREATE TABLE sneaky (id int)",
        "ALTER ROLE fieldtwin_app SUPERUSER",
        "GRANT fieldtwin TO CURRENT_USER",
    ],
)
def test_real_application_login_cannot_escalate_or_bypass(real_login, sql):
    denied(real_login, sql)


def test_real_application_login_can_read(real_login):
    assert real_login.execute("SELECT count(*) FROM domain_boundaries").fetchone()[0] > 0
    row = real_login.execute(
        "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert row == (False,)


def test_application_cannot_insert_any_scenario_mapping(app):
    denied(
        app,
        """INSERT INTO scenario_mappings (scenario_id, target_asset_id, telemetry_event_id, original_source_instance_id,
             transformation_config, compatibility_assessment_id, mapping_provenance)
           VALUES ('S1', 'A-03', %s, %s, '{}', '3w-aether:EVENT_CLASS:QUICK_RESTRICTION_IN_PCK:v1', 'REPLAYED')""",
        (REAL_EVENT, REAL_INSTANCE),
    )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO observations (source_system_id, source_record_id, observation_type, metric_name, quality_flag, provenance_class, original_record_uri, transformation_id) VALUES ('petrobras_3w', 'x', 'POINT_VALUE', 'm', 'q', 'OBSERVED', 'u', '3w.real_series.to_observation@1')",
        "INSERT INTO asset_observation_links (asset_id, observation_id, relationship_type, verification_status, method_version, provenance_class, scenario_id) VALUES ('A-03', 1, 'EXPERIMENTAL_SCENARIO_LINK', 'UNVERIFIED', 'x', 'SYNTHETIC', 'S1')",
        "INSERT INTO shared_events (event_id, schema_version, domain, event_kind, event_class, source_system_id, evidence, provenance_class, transformation_id) VALUES ('x', 1, 'OFFSHORE_BENCHMARK', 'SOURCE_LABEL', 'c', 'petrobras_3w', '{\"a\": 1}', 'DERIVED', 't')",
        "INSERT INTO scenario_runs (scenario_run_id) VALUES ('x')",
    ],
)
def test_application_cannot_write_observations_links_events_or_runs(app, sql):
    denied(app, sql)


def test_application_can_do_its_actual_work(app):
    assert app.execute("SELECT count(*) FROM source_assets").fetchone()[0] > 0
    row = app.execute(
        """INSERT INTO audit_events (actor_id, operation, target_id, correlation_id)
           VALUES ('a', 'o', 't', 'c') RETURNING event_id"""
    ).fetchone()
    assert row[0] > 0


def test_application_is_still_bound_by_decision_constraints(app):
    with pytest.raises(psycopg.errors.CheckViolation):
        with app.transaction():
            app.execute(
                """INSERT INTO reconciliation_decisions (module, subject_type, subject_id, object_type, object_id,
                     relationship_type, method, evidence, verification_status, provenance_class, algorithm_version)
                   VALUES ('IDENTITY', 'SOURCE_ASSET', 'a', 'ASSET', 'A-03', 'SAME_AS', 'AUTHORITATIVE_IDENTIFIER',
                     '{"a": 1}', 'VERIFIED', 'DERIVED', 'x@1')"""
            )


def test_new_tables_default_to_read_only_for_the_application(db):
    db.execute("CREATE TABLE later_table (id int)")
    db.execute("INSERT INTO later_table VALUES (1)")
    db.execute("SET LOCAL ROLE fieldtwin_app")
    assert db.execute("SELECT count(*) FROM later_table").fetchone()[0] == 1
    denied(db, "INSERT INTO later_table VALUES (2)")


# Provenance chain


@pytest.fixture
def run_data(db):
    config = load_config()
    persist(db, config, execute(config), URIS, load_rules()["algorithms"]["scenario"])
    return db


def refused(conn, sql, params=None, error=psycopg.errors.IntegrityError, match=None):
    with pytest.raises(error, match=match):
        with conn.transaction():
            conn.execute(sql, params)


ORPHAN = """INSERT INTO observations (source_system_id, source_record_id, observation_type, metric_name, quality_flag,
             provenance_class, original_record_uri, transformation_id, sensor_tag_id, scenario_id, scenario_run_id)
           VALUES ('aether_synthetic', 'orphan', 'TELEMETRY_SERIES', 'm', 'COMPLETE', 'SYNTHETIC', 'u',
             'aether.simulator.to_series@1', %s, %s, %s)"""


def test_every_synthetic_observation_has_a_complete_chain(run_data):
    rows = run_data.execute(
        """SELECT count(*), count(*) FILTER (WHERE chain_complete),
                  count(DISTINCT parameter_set_sha256), count(DISTINCT simulator_version)
           FROM v_synthetic_provenance_chain"""
    ).fetchone()
    assert rows == (8, 8, 1, 1)
    row = run_data.execute(
        """SELECT asset_id, sensor_tag_id, scenario_id, scenario_run_id, simulator_name, random_seed
           FROM v_synthetic_provenance_chain WHERE sensor_tag_id = 'aether_synthetic:A-03.PT-WH' LIMIT 1"""
    ).fetchone()
    assert row[0] == "A-03" and row[2] == "AETHER-FAULT-001" and row[5] == 30010


def test_synthetic_observation_without_a_run_is_refused(run_data):
    refused(run_data, ORPHAN, ("aether_synthetic:A-03.PT-WH", None, None))


def test_synthetic_observation_without_a_sensor_is_refused(run_data):
    refused(run_data, ORPHAN, (None, "AETHER-FAULT-001", "AETHER-FAULT-001:v1:fault"))


def test_synthetic_observation_cannot_use_a_3w_sensor(run_data):
    refused(
        run_data,
        ORPHAN,
        ("petrobras_3w:PT-P", "AETHER-FAULT-001", "AETHER-FAULT-001:v1:fault"),
        match="cannot use a sensor",
    )


def test_source_observation_cannot_claim_a_run(run_data):
    refused(
        run_data,
        """UPDATE observations SET scenario_run_id = 'AETHER-FAULT-001:v1:fault', scenario_id = 'AETHER-FAULT-001'
           WHERE source_system_id = 'petrobras_3w'""",
    )


def test_observation_scenario_must_match_its_run(run_data):
    run_data.execute(
        """INSERT INTO scenarios (scenario_id, scenario_name, scenario_description, target_facility_id, scenario_version, random_seed)
           VALUES ('OTHER', 'o', 'o', 'AETHER-FIELD', 1, 1)"""
    )
    refused(
        run_data,
        "UPDATE observations SET scenario_id = 'OTHER' WHERE scenario_run_id IS NOT NULL",
        error=psycopg.errors.ForeignKeyViolation,
    )


def test_link_must_name_the_asset_the_sensor_is_on(run_data):
    refused(
        run_data,
        "UPDATE asset_observation_links SET asset_id = 'C-01' WHERE asset_id IS NOT NULL",
        match="sensor is on",
    )


def test_synthetic_sensor_must_be_on_a_fictional_asset(db):
    refused(
        db,
        "UPDATE sensor_tags SET fictional_asset_id = NULL WHERE source_system_id = 'aether_synthetic'",
    )
    refused(
        db,
        "UPDATE sensor_tags SET fictional_asset_id = 'nm_ocd:well:30-015-90001' WHERE source_system_id = 'aether_synthetic'",
    )
    refused(
        db,
        "UPDATE sensor_tags SET fictional_asset_id = 'A-03' WHERE source_system_id = 'petrobras_3w'",
    )


def test_audit_covers_the_provenance_chain(run_data):
    findings = {f.name: f.violations for f in audit_provenance(run_data)}
    assert findings["synthetic_observation_chain_incomplete"] == 0
    assert all(v == 0 for v in findings.values())
