"""Attempts to bypass the Gate 7 decision workflow. The database must refuse each one.

The field scenario runs are recorded inside each rolled-back test transaction, so real synthetic runs
exist to reference. Alarms and recommendations below are test inputs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from packages.decision_engine.workflow import Decision
from pipelines.decision.decide import record_decision

pytestmark = pytest.mark.db
RUN = "AETHER-FAULT-001-NET:v1:fault"
T0 = datetime(2040, 1, 4, 12, tzinfo=UTC)
TERMS = [
    {"name": "alarm_started", "points": 30, "input": "1", "rule": "r"},
    {"name": "consequence", "points": 20, "input": "0.5", "rule": "r"},
]


@pytest.fixture
def runs(db):
    from pipelines.reconcile.run import load_rules
    from pipelines.synthetic.aether_field import execute_all, persist_all

    persist_all(db, execute_all(), {}, load_rules()["algorithms"]["scenario"])
    db.execute(
        """INSERT INTO detector_alarms (alarm_id, scenario_id, scenario_run_id, started_at, score, threshold, model_id,
             model_version, model_sha256, evidence, earlier_starts_in_lookback, first_alarm_at, provenance_class,
             input_provenance)
           VALUES ('ALM-1', 'AETHER-FAULT-001-NET', %s, %s, 2.0, 1.5, 'm', '1', %s, '[]', 0, %s, 'INFERRED', 'SYNTHETIC')""",
        (RUN, T0, "0" * 64, T0),
    )
    return db


def _recommendation(
    db, rec_id="REC-1", score=50, candidates=("GS-A", "A-02"), action="FIELD_INSPECTION", band="P2"
):
    db.execute(
        """INSERT INTO recommendations (recommendation_id, alarm_id, scenario_id, scenario_run_id, decided_at, action,
             candidate_assets, suppressed_assets, priority_score, priority_band, respond_within_h, terms, explanation,
             rules_version, provenance_class)
           VALUES (%s, 'ALM-1', 'AETHER-FAULT-001-NET', %s, %s, %s, %s, '{}', %s, %s, 72, %s, '["why"]', 3, 'SYNTHETIC')""",
        (rec_id, RUN, T0, action, list(candidates), score, band, json.dumps(TERMS)),
    )


def _work_order(db, asset="GS-A", rec_id="REC-1", status="RECOMMENDED", external="WO-1"):
    work_order_id = db.execute(
        """INSERT INTO work_orders (scenario_id, asset_id, recommended_action, severity, priority, status,
             evidence_reference, external_id, recommendation_id, priority_band)
           VALUES ('AETHER-FAULT-001-NET', %s, 'FIELD_INSPECTION', 'P2', 50, %s, %s, %s, %s, 'P2')
           RETURNING work_order_id""",
        (asset, status, rec_id, external, rec_id),
    ).fetchone()[0]
    db.execute(
        """INSERT INTO work_order_transitions (work_order_id, sequence, decision, from_status, to_status, actor_id,
             actor_kind, actor_role, justification, decided_at)
           VALUES (%s, 0, 'CREATE', NULL, 'RECOMMENDED', 'decision-engine', 'SYSTEM', 'DECISION_ENGINE', 'created', %s)""",
        (work_order_id, T0),
    )
    return work_order_id


def refused(db, sql, params=None, error=psycopg.errors.CheckViolation):
    with pytest.raises(error):
        with db.transaction():
            db.execute(sql, params)


def test_score_must_equal_its_terms(runs):
    with pytest.raises(psycopg.errors.CheckViolation):
        with runs.transaction():
            _recommendation(runs, score=99)


def test_recommendations_name_fictional_assets_only(runs):
    with pytest.raises(psycopg.errors.CheckViolation):
        with runs.transaction():
            _recommendation(runs, candidates=("nm_ocd:well:30-015-90001",))


def test_a_dispatch_needs_a_band_and_a_suppression_has_none(runs):
    with pytest.raises(psycopg.errors.CheckViolation):
        with runs.transaction():
            _recommendation(runs, band=None)
    with pytest.raises(psycopg.errors.CheckViolation):
        with runs.transaction():
            _recommendation(runs, action="NO_ACTION_PLANNED_OPERATION")


def test_an_alarm_score_must_cross_its_threshold(runs):
    refused(
        runs,
        """INSERT INTO detector_alarms (alarm_id, scenario_id, scenario_run_id, started_at, score, threshold, model_id,
             model_version, model_sha256, evidence, earlier_starts_in_lookback, first_alarm_at, provenance_class,
             input_provenance)
           VALUES ('ALM-2', 'AETHER-FAULT-001-NET', %s, %s, 1.0, 1.5, 'm', '1', %s, '[]', 0, %s, 'INFERRED', 'SYNTHETIC')""",
        (RUN, T0, "0" * 64, T0),
    )


def test_work_order_must_match_its_recommendation_and_start_recommended(runs):
    _recommendation(runs)
    with pytest.raises(psycopg.errors.CheckViolation):
        with runs.transaction():
            _work_order(runs, asset="A-02")
    with pytest.raises(psycopg.errors.CheckViolation):
        with runs.transaction():
            _work_order(runs, status="APPROVED")


def test_status_cannot_change_without_a_transition_and_audit_event(runs):
    _recommendation(runs)
    work_order_id = _work_order(runs)
    refused(
        runs,
        "UPDATE work_orders SET status = 'APPROVED' WHERE work_order_id = %s",
        (work_order_id,),
    )
    runs.execute(
        """INSERT INTO work_order_transitions (work_order_id, sequence, decision, from_status, to_status, actor_id,
             actor_kind, actor_role, justification, decided_at)
           VALUES (%s, 1, 'APPROVE', 'RECOMMENDED', 'APPROVED', 'pat', 'HUMAN', 'MAINTENANCE_SUPERVISOR', 'ok', %s)""",
        (work_order_id, T0 + timedelta(hours=1)),
    )
    refused(
        runs,
        "UPDATE work_orders SET status = 'APPROVED' WHERE work_order_id = %s",
        (work_order_id,),
    )


@pytest.mark.parametrize(
    ("decision", "from_status", "to_status", "kind", "role"),
    [
        ("APPROVE", "RECOMMENDED", "APPROVED", "SYSTEM", "MAINTENANCE_SUPERVISOR"),
        ("APPROVE", "RECOMMENDED", "APPROVED", "HUMAN", "FIELD_TECHNICIAN"),
        ("COMPLETE", "RECOMMENDED", "COMPLETED", "HUMAN", "FIELD_TECHNICIAN"),
        ("APPROVE", "RECOMMENDED", "COMPLETED", "HUMAN", "MAINTENANCE_SUPERVISOR"),
        ("CREATE", None, "RECOMMENDED", "HUMAN", "MAINTENANCE_SUPERVISOR"),
    ],
)
def test_disallowed_transitions_are_refused(runs, decision, from_status, to_status, kind, role):
    _recommendation(runs)
    work_order_id = _work_order(runs)
    refused(
        runs,
        """INSERT INTO work_order_transitions (work_order_id, sequence, decision, from_status, to_status, actor_id,
             actor_kind, actor_role, justification, decided_at) VALUES (%s, 1, %s, %s, %s, 'x', %s, %s, 'why', %s)""",
        (work_order_id, decision, from_status, to_status, kind, role, T0 + timedelta(hours=1)),
    )


def test_transitions_are_ordered_and_append_only(runs):
    _recommendation(runs)
    work_order_id = _work_order(runs)
    refused(
        runs,
        """INSERT INTO work_order_transitions (work_order_id, sequence, decision, from_status, to_status, actor_id,
             actor_kind, actor_role, justification, decided_at)
           VALUES (%s, 1, 'APPROVE', 'RECOMMENDED', 'APPROVED', 'pat', 'HUMAN', 'MAINTENANCE_SUPERVISOR', 'ok', %s)""",
        (work_order_id, T0 - timedelta(hours=1)),
    )
    refused(
        runs,
        "UPDATE work_order_transitions SET justification = 'edited'",
        error=psycopg.errors.RestrictViolation,
    )
    refused(runs, "DELETE FROM recommendations", error=psycopg.errors.RestrictViolation)


def test_a_person_can_approve_and_complete_through_the_guarded_path(runs):
    _recommendation(runs)
    _work_order(runs)
    assert (
        record_decision(
            runs,
            "WO-1",
            Decision.APPROVE,
            "pat",
            "HUMAN",
            "MAINTENANCE_SUPERVISOR",
            "Evidence reviewed.",
            T0 + timedelta(hours=1),
        )
        == "APPROVED"
    )
    assert (
        record_decision(
            runs,
            "WO-1",
            Decision.COMPLETE,
            "sam",
            "HUMAN",
            "FIELD_TECHNICIAN",
            "Visited.",
            T0 + timedelta(hours=9),
        )
        == "COMPLETED"
    )
    audits = runs.execute("SELECT count(*) FROM audit_events WHERE target_id = 'WO-1'").fetchone()[
        0
    ]
    approvals = runs.execute("SELECT actor_kind FROM approval_events").fetchall()
    assert audits == 2 and approvals == [("HUMAN",)]
    with pytest.raises(ValueError):
        record_decision(
            runs,
            "WO-1",
            Decision.APPROVE,
            "pat",
            "HUMAN",
            "MAINTENANCE_SUPERVISOR",
            "again",
            T0 + timedelta(hours=10),
        )


def test_the_application_role_can_decide_but_not_recommend(runs):
    _recommendation(runs)
    _work_order(runs)
    runs.execute("SET LOCAL ROLE fieldtwin_app")
    assert (
        record_decision(
            runs,
            "WO-1",
            Decision.REQUEST_EVIDENCE,
            "pat",
            "HUMAN",
            "MAINTENANCE_SUPERVISOR",
            "Need a second alarm.",
            T0 + timedelta(hours=1),
        )
        == "NEEDS_EVIDENCE"
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with runs.transaction():
            _recommendation(runs, rec_id="REC-2")
