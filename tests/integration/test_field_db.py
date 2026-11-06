"""The field simulation recorded in the canonical schema, on a real PostgreSQL."""

from __future__ import annotations

import psycopg
import pytest

from packages.reconciliation.provenance import audit_provenance
from packages.scenario_engine.network_graph import ALLOWED_CONNECTIONS, build_graph, load_network
from pipelines.reconcile.run import load_rules
from pipelines.synthetic.aether_field import execute_all, persist_all

pytestmark = pytest.mark.db
ALGORITHM = load_rules()["algorithms"]["scenario"]


@pytest.fixture
def recorded(db):
    totals = persist_all(db, execute_all(), {}, ALGORITHM)
    return db, totals


def value(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def test_six_runs_are_recorded_with_every_series_linked(recorded):
    db, totals = recorded
    assert totals == {"runs": 6, "series": 234, "links": 234, "events": 9}
    assert (
        value(
            db,
            "SELECT count(*) FROM scenario_runs WHERE provenance_class = 'SYNTHETIC' AND simulator_name = 'aether-field-network'",
        )
        == 6
    )


def test_every_observation_has_a_complete_chain_to_asset_sensor_run_and_parameters(recorded):
    db, _ = recorded
    row = db.execute(
        """SELECT count(*), count(*) FILTER (WHERE chain_complete), count(DISTINCT parameter_set_sha256)
           FROM v_synthetic_provenance_chain WHERE simulator_name = 'aether-field-network'"""
    ).fetchone()
    assert row == (234, 234, 6)
    assert (
        value(db, "SELECT count(*) FROM v_synthetic_provenance_chain WHERE NOT asset_is_fictional")
        == 0
    )


def test_series_link_to_the_asset_each_sensor_is_on(recorded):
    db, _ = recorded
    rows = db.execute(
        """SELECT DISTINCT asset_id, linked_asset_id FROM v_synthetic_provenance_chain
           WHERE sensor_tag_id IN ('aether_synthetic:MANIFOLD.PT', 'aether_synthetic:C-02.STATE')"""
    ).fetchall()
    assert sorted(rows) == [("C-02", "C-02"), ("MANIFOLD", "MANIFOLD")]


def test_dropout_is_visible_in_series_metadata(recorded):
    db, _ = recorded
    row = db.execute(
        """SELECT quality_flag, null_count FROM observations
           WHERE source_record_id = 'AETHER-NET-COMM-DROPOUT:v1:fault#B-01.FT'"""
    ).fetchone()
    assert row == ("PARTIAL", 144)


def test_events_reach_the_shared_contract_by_fault_domain(recorded):
    db, _ = recorded
    rows = dict(
        db.execute(
            """SELECT evidence->>'fault_domain', count(*) FROM shared_events
               WHERE scenario_id LIKE 'AETHER-NET%' OR scenario_id = 'AETHER-FAULT-001-NET' GROUP BY 1"""
        ).fetchall()
    )
    assert rows == {"PHYSICAL": 2, "SENSOR": 2, "COMMUNICATION": 2, "PLANNED": 3}


def test_recording_twice_adds_nothing(recorded):
    db, _ = recorded
    before = value(db, "SELECT count(*) FROM observations")
    again = persist_all(db, execute_all(), {}, ALGORITHM)
    assert again == {"already_recorded": 6}
    assert value(db, "SELECT count(*) FROM observations") == before


def test_field_records_touch_no_source_data(recorded):
    db, _ = recorded
    assert value(db, "SELECT count(*) FROM scenario_mappings") == 0
    assert (
        value(
            db,
            "SELECT count(*) FROM asset_observation_links l JOIN observations o USING (observation_id) WHERE o.source_system_id <> 'aether_synthetic'",
        )
        == 0
    )
    assert [f.name for f in audit_provenance(db) if f.violations] == []


# Physical network in the database


def test_stored_graph_matches_the_validated_configuration(db):
    graph = build_graph(load_network())
    assert value(db, "SELECT count(*) FROM physical_nodes") == len(graph.nodes)
    assert value(db, "SELECT count(*) FROM physical_edges") == len(graph.edges)
    assert value(db, "SELECT count(*) FROM physical_nodes WHERE node_type = 'WELLHEAD'") == 12
    assert value(db, "SELECT count(*) FROM physical_edges WHERE edge_type = 'COMPRESSION'") == 4


def test_physical_graph_is_stored_apart_from_evidence_and_identity(db):
    """Neither identity nor evidence tables can reference a physical edge."""
    rows = db.execute(
        """SELECT count(*) FROM information_schema.constraint_column_usage
           WHERE table_name IN ('physical_nodes', 'physical_edges')
             AND constraint_name IN (SELECT constraint_name FROM information_schema.table_constraints
               WHERE table_name IN ('source_identifiers', 'reconciliation_decisions', 'asset_relationships', 'source_reconciliation_evidence'))"""
    ).fetchone()
    assert rows[0] == 0


def test_python_and_database_connection_rules_match(db):
    stored = set(
        db.execute(
            "SELECT edge_type, from_node_type, to_node_type FROM physical_connection_rules"
        ).fetchall()
    )
    assert stored == {(e.value, a.value, b.value) for e, a, b in ALLOWED_CONNECTIONS}


@pytest.mark.parametrize(
    ("edge_type", "source", "target"),
    [
        ("GATHERING_SEGMENT", "MANIFOLD", "HDR-A"),
        ("COMPRESSION", "COMP-SUCTION", "WH:A-01"),
        ("WELL_INFLOW", "WH:A-01", "HDR-A"),
        ("FLOWLINE", "HDR-A", "MANIFOLD"),
    ],
)
def test_invalid_physical_connections_are_refused(db, edge_type, source, target):
    with pytest.raises(psycopg.errors.CheckViolation, match="invalid physical connection"):
        with db.transaction():
            db.execute(
                """INSERT INTO physical_edges (edge_id, edge_type, from_node_id, to_node_id, element_asset_id, length_m, diameter_m, network_version, provenance_class)
                   VALUES ('BAD', %s, %s, %s, 'GS-A', 9000, 0.1, 1, 'SYNTHETIC')""",
                (edge_type, source, target),
            )


def test_physical_graph_cannot_reference_a_real_asset_or_claim_observed(db):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db.transaction():
            db.execute(
                """INSERT INTO physical_nodes (node_id, facility_id, node_type, asset_id, network_version, provenance_class)
                   VALUES ('X', 'AETHER-FIELD', 'JUNCTION', 'nm_ocd:well:30-015-90001', 1, 'SYNTHETIC')"""
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            db.execute("UPDATE physical_nodes SET provenance_class = 'OBSERVED'")


def test_application_role_can_read_the_network_but_not_change_it(db):
    db.execute("SET LOCAL ROLE fieldtwin_app")
    assert value(db, "SELECT count(*) FROM physical_edges") > 0
    for sql in ("DELETE FROM physical_edges", "UPDATE physical_nodes SET node_type = 'SITE'"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction():
                db.execute(sql)
