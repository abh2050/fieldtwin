"""The reconciliation engine and scenario pipeline, end to end on committed CI fixtures."""

from __future__ import annotations

import pytest

from packages.reconciliation.provenance import audit_provenance
from packages.reconciliation.review import ReviewError, apply_review, review_queue
from packages.repositories.lineage import telemetry_lineage
from packages.scenario_engine.config import load_config
from pipelines.normalize.petrobras_3w_events import label_onset_offset_s, load_benchmark_events
from pipelines.reconcile.run import geospatial_decisions, load_rules, reconcile_all
from pipelines.synthetic.aether_fault_001 import execute, persist, prioritization_payload
from tests.conftest import CI_WORKSPACE

pytestmark = pytest.mark.db
RULES = load_rules()
WELLS_IN_FIXTURE = 8
FIXTURE_URIS = {"nominal": "data/gold/nominal.parquet", "fault": "data/gold/fault.parquet"}


@pytest.fixture
def engine(db):
    reconcile_all(db, RULES)
    return db


def count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def test_every_ocd_well_is_verified_by_identifier_only(engine):
    rows = engine.execute(
        """SELECT verification_status, method, count(*) FROM reconciliation_decisions
           WHERE relationship_type = 'SAME_AS' AND module = 'IDENTITY' GROUP BY 1, 2"""
    ).fetchall()
    assert rows == [("VERIFIED", "AUTHORITATIVE_IDENTIFIER", WELLS_IN_FIXTURE)]


def test_decisions_carry_every_required_field(engine):
    missing = count(
        engine,
        """SELECT count(*) FROM reconciliation_decisions
           WHERE subject_id IS NULL OR relationship_type IS NULL OR method IS NULL OR evidence IS NULL
              OR verification_status IS NULL OR algorithm_version IS NULL OR decided_at IS NULL""",
    )
    assert missing == 0
    assert count(engine, "SELECT count(*) FROM reconciliation_decisions") > 0


def test_no_crosswalk_exists_between_3w_and_ocd(engine):
    row = engine.execute(
        "SELECT verification_status, method FROM reconciliation_decisions WHERE relationship_type = 'NO_CROSSWALK'"
    ).fetchone()
    assert row == ("UNRESOLVED", "NO_SHARED_IDENTIFIER")


def test_nothing_real_relates_to_a_fictional_asset(engine):
    assert (
        count(
            engine,
            "SELECT count(*) FROM reconciliation_decisions WHERE object_type = 'ASSET' AND subject_type <> 'SCENARIO_RUN'",
        )
        == 0
    )
    assert (
        count(
            engine,
            "SELECT count(*) FROM source_identifiers si JOIN assets a ON a.asset_id = si.canonical_asset_id",
        )
        == 0
    )


def test_native_tags_keep_their_own_equipment_class(engine):
    rows = engine.execute(
        """SELECT d.subject_id, m.equipment_class_id, t.equipment_class_id
           FROM reconciliation_decisions d
           JOIN measurement_definitions m ON m.measurement_definition_id = d.object_id
           JOIN sensor_tags t ON t.tag_id = d.subject_id
           WHERE d.module = 'SEMANTIC' AND d.verification_status <> 'REJECTED'"""
    ).fetchall()
    assert len(rows) == 31
    assert all(row[1] == row[2] for row in rows)


def test_3w_pressures_stay_unresolved_after_reconciliation(engine):
    assert (
        count(
            engine,
            "SELECT count(*) FROM reconciliation_decisions WHERE module = 'SEMANTIC' AND verification_status = 'UNRESOLVED'",
        )
        == 10
    )


def test_subsea_tags_mapping_to_aether_are_recorded_as_rejected(engine):
    rows = engine.execute(
        """SELECT DISTINCT verification_status FROM reconciliation_decisions
           WHERE subject_id = 'petrobras_3w:PT-P' AND object_id LIKE 'aether_%%'"""
    ).fetchall()
    assert rows == [("REJECTED",)]
    assert (
        count(
            engine,
            "SELECT count(*) FROM sensor_tag_mappings m JOIN sensor_tags t USING (tag_id) WHERE t.source_system_id = 'petrobras_3w' AND m.measurement_definition_id LIKE 'aether_%%'",
        )
        == 0
    )


def test_excluded_wells_are_never_proximity_candidates(db):
    decisions = geospatial_decisions(db, RULES, radius_m=5000.0)
    assert decisions
    named = {d.subject_id for d in decisions} | {d.object_id for d in decisions}
    for excluded in ("30-015-90005", "30-015-90006", "30-015-90007"):
        assert f"nm_ocd:well:{excluded}" not in named
    assert all(d.verification_status.value == "UNVERIFIED" for d in decisions)
    assert all(d.relationship_type.value == "PROXIMITY_CANDIDATE" for d in decisions)


def test_reconciliation_is_repeatable_without_new_rows(engine):
    before = count(engine, "SELECT count(*) FROM reconciliation_decisions")
    results = reconcile_all(engine, RULES)
    assert results["identity"] == results["semantic"] == "already_run"
    assert results["geospatial"] in ("already_run", 0)  # The fixture has no pairs within 100 m.
    assert count(engine, "SELECT count(*) FROM reconciliation_decisions") == before


def test_provenance_audit_is_clean(engine):
    findings = audit_provenance(engine)
    assert len(findings) >= 13
    assert [f.name for f in findings if f.violations] == []


# Review


def candidate(conn):
    from packages.reconciliation.review import store_decisions

    store_decisions(conn, geospatial_decisions(conn, RULES, radius_m=5000.0))
    return conn.execute(
        "SELECT decision_id FROM reconciliation_decisions WHERE relationship_type = 'PROXIMITY_CANDIDATE' LIMIT 1"
    ).fetchone()[0]


def unresolved(conn):
    return conn.execute(
        "SELECT decision_id FROM reconciliation_decisions WHERE module = 'SEMANTIC' AND verification_status = 'UNRESOLVED' LIMIT 1"
    ).fetchone()[0]


def test_unreviewed_candidates_wait_in_the_queue(db):
    identifier = candidate(db)
    assert identifier in {row["decision_id"] for row in review_queue(db, 1000)}
    row = db.execute(
        "SELECT verification_status FROM reconciliation_decisions WHERE decision_id = %s",
        (identifier,),
    ).fetchone()
    assert row == ("UNVERIFIED",)


def test_proximity_cannot_be_approved_even_by_a_reviewer(db):
    identifier = candidate(db)
    with pytest.raises(ReviewError, match="can't be approved"):
        apply_review(db, identifier, "reviewer", "APPROVE", "They look like the same well to me.")
    assert (
        count(
            db,
            "SELECT count(*) FROM reconciliation_decisions WHERE supersedes_decision_id = %s",
            identifier,
        )
        == 0
    )


def test_rejecting_a_candidate_supersedes_it_and_leaves_history(db):
    identifier = candidate(db)
    new = apply_review(db, identifier, "reviewer", "REJECT", "These are separate wells on one pad.")
    assert (
        count(
            db,
            "SELECT count(*) FROM v_current_reconciliation_decisions WHERE decision_id = %s",
            identifier,
        )
        == 0
    )
    row = db.execute(
        "SELECT verification_status, method, supersedes_decision_id FROM reconciliation_decisions WHERE decision_id = %s",
        (new,),
    ).fetchone()
    assert row == ("REJECTED", "HUMAN_REVIEW", identifier)
    assert (
        count(
            db, "SELECT count(*) FROM reconciliation_decisions WHERE decision_id = %s", identifier
        )
        == 1
    )


def test_request_for_evidence_changes_no_status(db):
    identifier = candidate(db)
    assert (
        apply_review(db, identifier, "reviewer", "REQUEST_EVIDENCE", "Need a survey plat first.")
        is None
    )
    assert (
        count(db, "SELECT count(*) FROM reconciliation_reviews WHERE decision_id = %s", identifier)
        == 1
    )
    assert identifier not in {row["decision_id"] for row in review_queue(db, 1000)}


def insert_unresolved_identity(conn):
    from packages.domain.models import ProvenanceClass
    from packages.domain.reconciliation import EntityType
    from packages.reconciliation.identity import RecordRef, match_identity
    from packages.reconciliation.review import store_decisions

    a = RecordRef(EntityType.SOURCE_ASSET, "nm_ocd:well:30-015-90002", "nm_ocd", {}, "A")
    b = RecordRef(EntityType.SOURCE_RECORD, "record", "nm_ocd", {}, "A")
    store_decisions(conn, [match_identity(a, b, {"API_NUMBER"}, "review-test@1")])
    assert ProvenanceClass.DERIVED
    return conn.execute(
        "SELECT decision_id FROM reconciliation_decisions WHERE algorithm_version = 'review-test@1'"
    ).fetchone()[0]


def test_approving_identity_needs_an_authoritative_identifier(db):
    identifier = insert_unresolved_identity(db)
    with pytest.raises(ReviewError, match="authoritative identifier"):
        apply_review(db, identifier, "reviewer", "APPROVE", "The names and pad match exactly.")


def test_approved_identity_is_verified_and_distinguishable_from_automatic(db):
    identifier = insert_unresolved_identity(db)
    new = apply_review(
        db, identifier, "reviewer", "APPROVE", "Confirmed from the OCD well file.",
        {"authoritative_identifier": "API_NUMBER from a filed form"},
    )  # fmt: skip
    row = db.execute(
        "SELECT verification_status, method, review_id IS NOT NULL FROM reconciliation_decisions WHERE decision_id = %s",
        (new,),
    ).fetchone()
    assert row == ("VERIFIED", "HUMAN_REVIEW", True)


def test_review_needs_a_real_rationale(db):
    identifier = candidate(db)
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            apply_review(db, identifier, "reviewer", "REJECT", "no")


# Scenario


@pytest.fixture
def scenario(db):
    config = load_config()
    results = execute(config)
    counts = persist(db, config, results, FIXTURE_URIS, RULES["algorithms"]["scenario"])
    return db, config, results, counts


def test_scenario_records_two_synthetic_runs_on_well_a03(scenario):
    db, config, results, counts = scenario
    assert counts == {"runs": 2, "series": 8, "links": 8, "events": 2, "assignments": 2}
    rows = db.execute(
        "SELECT case_name, target_asset_id, affected_asset_id, provenance_class, random_seed, fault_onset_offset_s FROM scenario_runs ORDER BY 1"
    ).fetchall()
    assert rows == [
        ("fault", "A-03", "GS-A", "SYNTHETIC", 30010, config.restriction.onset_offset_s),
        ("nominal", "A-03", "GS-A", "SYNTHETIC", 30010, None),
    ]


def test_scenario_uses_no_3w_data_at_all(scenario):
    db, *_ = scenario
    assert count(db, "SELECT count(*) FROM scenario_mappings") == 0
    assert (
        count(
            db,
            "SELECT count(*) FROM observations WHERE scenario_run_id IS NOT NULL AND source_system_id <> 'aether_synthetic'",
        )
        == 0
    )
    assert (
        count(
            db,
            "SELECT count(*) FROM asset_observation_links l JOIN observations o USING (observation_id) WHERE o.source_system_id = 'petrobras_3w'",
        )
        == 0
    )
    assert (
        count(
            db,
            "SELECT count(*) FROM shared_events WHERE domain = 'AETHER_SYNTHETIC' AND telemetry_event_id IS NOT NULL",
        )
        == 0
    )


def test_simulated_series_are_experimental_links_never_measured_at(scenario):
    db, *_ = scenario
    rows = db.execute(
        """SELECT DISTINCT l.relationship_type, l.verification_status, l.provenance_class
           FROM asset_observation_links l JOIN observations o USING (observation_id)
           WHERE o.source_system_id = 'aether_synthetic'"""
    ).fetchall()
    assert rows == [("EXPERIMENTAL_SCENARIO_LINK", "UNVERIFIED", "SYNTHETIC")]


def test_run_preserves_parameters_seed_and_invariants(scenario):
    db, config, results, _ = scenario
    row = db.execute(
        "SELECT parameters, invariants, config_sha256, output_sha256 FROM scenario_runs WHERE case_name = 'fault'"
    ).fetchone()
    assert row[0]["gathering_segment"]["length_m"] == config.gathering_segment.length_m
    assert row[0]["simulator"]["seed"] == config.simulator.seed
    assert {i["name"] for i in row[1]} == set(config.expected_invariants)
    assert all(i["passed"] for i in row[1])
    assert row[2] == config.canonical_sha256()
    assert row[3] == results["fault"][0].canonical_sha256()


def test_scenario_events_reach_the_shared_contract(scenario):
    db, config, *_ = scenario
    rows = db.execute(
        "SELECT event_kind, target_asset_id, affected_asset_id, onset_offset_s FROM shared_events WHERE domain = 'AETHER_SYNTHETIC' ORDER BY 1"
    ).fetchall()
    assert [r[0] for r in rows] == ["INTEGRATION_PROOF_RULE", "KNOWN_SYNTHETIC_ONSET"]
    assert rows[1][3] == config.restriction.onset_offset_s
    assert all(r[1:3] == ("A-03", "GS-A") for r in rows)


def test_persisting_twice_records_nothing_new(scenario):
    db, config, results, _ = scenario
    again = persist(db, config, results, FIXTURE_URIS, RULES["algorithms"]["scenario"])
    assert again == {"already_recorded": 1}
    assert count(db, "SELECT count(*) FROM scenario_runs") == 2


def test_prioritization_input_can_reach_a_simulated_work_order_table(scenario):
    """Minimal proof that the output fits later workflows. No score or decision is made."""
    db, config, results, _ = scenario
    run, _, events = results["fault"]
    payload = prioritization_payload(config, run, events)
    assert payload["asset_id"] == "A-03" and payload["priority_score"] is None
    db.execute(
        """INSERT INTO work_orders (scenario_id, asset_id, recommended_action, severity, priority, status, evidence_reference)
           VALUES (%s, %s, 'INTEGRATION TEST ONLY', 'NOT_ASSESSED', 0, 'NEEDS_EVIDENCE', %s)""",
        (payload["scenario_id"], payload["asset_id"], payload["event_id"]),
    )
    assert count(db, "SELECT count(*) FROM work_orders") == 1


def test_nominal_case_writes_no_prioritization_input(scenario):
    _, config, results, _ = scenario
    run, _, events = results["nominal"]
    assert prioritization_payload(config, run, events) is None


# 3W benchmark adapter


def test_adapter_preserves_3w_identity_and_adds_no_aether_link(db):
    assert load_benchmark_events(db, CI_WORKSPACE) == 3
    rows = db.execute(
        """SELECT s.provenance_class, e.real_or_simulated_source, s.evidence->>'source_instance_id', e.source_instance_id,
                  s.target_asset_id, s.scenario_id
           FROM shared_events s JOIN telemetry_events e ON e.event_id = s.telemetry_event_id"""
    ).fetchall()
    assert len(rows) == 3
    for provenance, origin, evidence_id, source_id, asset, scenario_id in rows:
        assert provenance == ("DERIVED" if origin == "REAL" else "SYNTHETIC")
        assert evidence_id == source_id
        assert asset is None and scenario_id is None


def test_adapter_leaves_source_records_untouched(db):
    before = telemetry_lineage(db, "petrobras_3w:2:WELL-00002_20131104004101")
    load_benchmark_events(db, CI_WORKSPACE)
    assert telemetry_lineage(db, "petrobras_3w:2:WELL-00002_20131104004101") == before


def test_adapter_flags_a_named_event_class_with_no_event_labels(db):
    load_benchmark_events(db, CI_WORKSPACE)
    labelled = db.execute(
        "SELECT parquet_uri, event_id FROM telemetry_events ORDER BY event_id"
    ).fetchall()
    flagged = {
        row[0]
        for row in db.execute(
            "SELECT source_record_key FROM data_quality_exceptions WHERE exception_type = 'BENCHMARK_INSTANCE_WITHOUT_EVENT_LABEL'"
        )
    }
    for uri, event_id in labelled:
        has_onset = label_onset_offset_s(CI_WORKSPACE / uri) is not None
        assert (event_id in flagged) == (not has_onset)
