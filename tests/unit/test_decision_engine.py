"""Gate 7 decision logic. Alarms here are test inputs built field by field, not a dataset."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pydantic
import pytest

from packages.decision_engine.economics import Asset, DetectorStats, Fault, Job, costs, simulate
from packages.decision_engine.rules import (
    Action,
    Alarm,
    Context,
    EvidenceSensor,
    PlannedOperation,
    evaluate,
)
from packages.decision_engine.topology import FieldTopology
from packages.decision_engine.workflow import (
    Actor,
    ActorKind,
    Decision,
    Status,
    TransitionError,
    create_work_order,
)
from packages.optimization.routing import Router, exact_tour, ortools_tour
from packages.scenario_engine.network_graph import build_graph, load_network
from pipelines.acquire.common.core import load_yaml

ROOT = Path(__file__).resolve().parents[2]
RULES = load_yaml(ROOT / "config" / "decision" / "gate7_rules.yaml")
T0 = datetime(2040, 1, 4, 12, tzinfo=UTC)
ENGINE = Actor(actor_id="decision-engine", kind=ActorKind.SYSTEM, role="DECISION_ENGINE")
SUPERVISOR = Actor(actor_id="pat", kind=ActorKind.HUMAN, role="MAINTENANCE_SUPERVISOR")


@pytest.fixture(scope="module")
def topo() -> FieldTopology:
    return FieldTopology(
        build_graph(load_network()), RULES["consequence"]["parallel_compressor_share"]
    )


def alarm(
    *sensors: tuple[str, str, bool], earlier: int = 0, first: datetime | None = None
) -> Alarm:
    return Alarm(
        alarm_id="ALM-test",
        scenario_id="S",
        scenario_run_id="S:v1:fault",
        started_at=T0,
        score=2.0,
        threshold=1.5,
        model_id="m",
        model_version="1",
        model_sha256="0" * 64,
        evidence=[
            EvidenceSensor(tag=t, asset_id=a, deviation=1.0, degraded_quality=d)
            for t, a, d in sensors
        ],
        earlier_starts_in_lookback=earlier,
        first_alarm_at=first or T0,
    )


# Topology


def test_consequence_comes_from_the_network(topo):
    assert topo.facts["A-03"].consequence_share == pytest.approx(1 / 12)
    assert topo.facts["GS-A"].consequence_share == pytest.approx(0.5)
    assert topo.facts["GS-TRUNK"].consequence_share == pytest.approx(1.0)
    assert topo.facts["C-02"].consequence_share == pytest.approx(0.25)
    assert "COMP-DISCHARGE" not in topo.facts


def test_a_valve_covers_the_assets_upstream_of_it(topo):
    covered = topo.assets_through("IV-B")
    assert {"GS-B", "HDR-B", "B-01", "FL-B-06"} <= covered
    assert not {"GS-A", "A-01", "GS-TRUNK"} & covered


# Rules


def test_score_is_the_sum_of_named_terms_and_never_a_probability(topo):
    rec = evaluate(
        alarm(("GS-A.DPT-NET", "GS-A", False), ("A-02.PT-WH", "A-02", False)),
        Context(),
        topo,
        RULES,
    )
    assert rec.action is Action.FIELD_INSPECTION
    assert rec.priority_score == sum(t.points for t in rec.terms) == 30 + 20
    assert rec.priority_band == "P2" and rec.respond_within_h == 72
    assert rec.failure_probability is None
    assert "not a failure probability" in rec.explanation[0]
    with pytest.raises(pydantic.ValidationError):
        rec.model_copy(update={"failure_probability": 0.4}).model_validate(
            {**rec.model_dump(), "failure_probability": 0.4}
        )


def test_the_work_order_targets_the_largest_consequence(topo):
    rec = evaluate(
        alarm(("A-03.FT", "A-03", False), ("C-01.FT", "C-01", False), ("B-05.FT", "B-05", False)),
        Context(),
        topo,
        RULES,
    )
    assert rec.candidate_assets == ["C-01", "A-03", "B-05"]
    order = create_work_order(rec, ENGINE)
    assert order.asset_id == "C-01" and order.status is Status.RECOMMENDED


def test_repeats_and_age_are_capped(topo):
    rec = evaluate(
        alarm(("GS-TRUNK.DPT-NET", "GS-TRUNK", False), earlier=9, first=T0 - timedelta(hours=500)),
        Context(),
        topo,
        RULES,
    )
    terms = {t.name: t.points for t in rec.terms}
    assert terms["repeated_alarms"] == RULES["evidence"]["repeat_alarm_cap"]
    assert terms["evidence_age"] == RULES["evidence"]["age_cap"]
    assert terms["consequence"] == 40 and rec.priority_band == "P1"


def test_planned_operations_suppress_and_are_explained(topo):
    planned = Context(
        planned_operations=[
            PlannedOperation(
                kind="CLOSE_VALVE",
                asset_id="IV-B",
                start=T0 - timedelta(hours=1),
                end=T0 + timedelta(hours=1),
            )
        ]
    )
    rec = evaluate(
        alarm(("GS-B.DPT-NET", "GS-B", False), ("B-01.PT-WH", "B-01", False)), planned, topo, RULES
    )
    assert rec.action is Action.NO_ACTION_PLANNED_OPERATION and rec.priority_band is None
    assert rec.suppressed_assets == ["GS-B", "B-01"]
    with pytest.raises(TransitionError):
        create_work_order(rec, ENGINE)
    # Partly covered: the uncovered candidate is still dispatched.
    mixed = evaluate(
        alarm(("GS-B.DPT-NET", "GS-B", False), ("A-01.PT-WH", "A-01", False)), planned, topo, RULES
    )
    assert mixed.action is Action.FIELD_INSPECTION and mixed.candidate_assets == ["A-01"]
    # After the window ends, nothing is suppressed.
    later = planned.model_copy(
        update={
            "planned_operations": [
                p.model_copy(update={"end": T0 - timedelta(minutes=1)})
                for p in planned.planned_operations
            ]
        }
    )
    assert (
        evaluate(alarm(("GS-B.DPT-NET", "GS-B", False)), later, topo, RULES).action
        is Action.FIELD_INSPECTION
    )


def test_degraded_evidence_goes_to_an_instrumentation_check(topo):
    rec = evaluate(alarm(("HDR-B.PT-NET", "HDR-B", True)), Context(), topo, RULES)
    assert rec.action is Action.CHECK_INSTRUMENTATION
    assert any("instrumentation" in line for line in rec.explanation)


def test_no_evidence_needs_more_evidence(topo):
    rec = evaluate(alarm(), Context(), topo, RULES)
    assert rec.action is Action.NEEDS_EVIDENCE and rec.priority_band is None


def test_open_inspection_request_adds_points(topo):
    rec = evaluate(
        alarm(("A-03.FT", "A-03", False)),
        Context(open_inspection_request_assets=["A-03"]),
        topo,
        RULES,
    )
    assert {t.name: t.points for t in rec.terms}["open_inspection_request"] == 10


def test_evaluation_is_deterministic(topo):
    a = alarm(("GS-A.DPT-NET", "GS-A", False))
    assert evaluate(a, Context(), topo, RULES) == evaluate(a, Context(), topo, RULES)


# Work orders


def _order(topo):
    return create_work_order(
        evaluate(alarm(("GS-A.DPT-NET", "GS-A", False)), Context(), topo, RULES), ENGINE
    )


def test_approval_path_and_audit(topo):
    order = _order(topo)
    order.apply(Decision.APPROVE, SUPERVISOR, "Evidence reviewed.", T0 + timedelta(hours=1))
    crew = Actor(actor_id="crew", kind=ActorKind.HUMAN, role="FIELD_TECHNICIAN")
    order.apply(Decision.COMPLETE, crew, "Visited.", T0 + timedelta(hours=8))
    assert order.status is Status.COMPLETED
    assert [(e.decision, e.before, e.after) for e in order.history] == [
        ("CREATE", None, Status.RECOMMENDED),
        (Decision.APPROVE, Status.RECOMMENDED, Status.APPROVED),
        (Decision.COMPLETE, Status.APPROVED, Status.COMPLETED),
    ]


@pytest.mark.parametrize(
    ("actor", "decision", "message"),
    [
        (ENGINE, Decision.APPROVE, "recommend only"),
        (
            Actor(actor_id="tech", kind=ActorKind.HUMAN, role="FIELD_TECHNICIAN"),
            Decision.APPROVE,
            "needs the",
        ),
        (SUPERVISOR, Decision.COMPLETE, "not allowed"),
        (SUPERVISOR, Decision.RESUBMIT, "not allowed"),
    ],
)
def test_refused_transitions(topo, actor, decision, message):
    order = _order(topo)
    with pytest.raises(TransitionError, match=message):
        order.apply(decision, actor, "Because.", T0 + timedelta(hours=1))
    assert order.status is Status.RECOMMENDED and len(order.history) == 1


def test_evidence_request_resubmit_and_reject(topo):
    order = _order(topo)
    order.apply(
        Decision.REQUEST_EVIDENCE, SUPERVISOR, "Need a second alarm.", T0 + timedelta(hours=1)
    )
    with pytest.raises(TransitionError):
        order.apply(Decision.APPROVE, SUPERVISOR, "Too early.", T0 + timedelta(hours=2))
    order.apply(Decision.RESUBMIT, SUPERVISOR, "Second alarm arrived.", T0 + timedelta(hours=3))
    order.apply(Decision.REJECT, SUPERVISOR, "Planned work explains it.", T0 + timedelta(hours=4))
    assert order.status is Status.REJECTED
    with pytest.raises(TransitionError):
        order.apply(Decision.APPROVE, SUPERVISOR, "Changed my mind.", T0 + timedelta(hours=5))


def test_decisions_need_justification_and_time_order(topo):
    order = _order(topo)
    with pytest.raises(TransitionError, match="justification"):
        order.apply(Decision.APPROVE, SUPERVISOR, "  ", T0 + timedelta(hours=1))
    with pytest.raises(TransitionError, match="time order"):
        order.apply(Decision.APPROVE, SUPERVISOR, "Fine.", T0 - timedelta(hours=1))


def test_only_the_engine_creates(topo):
    rec = evaluate(alarm(("GS-A.DPT-NET", "GS-A", False)), Context(), topo, RULES)
    with pytest.raises(TransitionError):
        create_work_order(rec, SUPERVISOR)


# Routing


def test_ortools_matches_exhaustive_search_on_small_tours():
    rng = np.random.default_rng(7)
    for n in range(2, 8):
        points = rng.uniform(0, 4000, (n, 2))

        def distance(i: int, j: int, p=points) -> float:
            return float(np.hypot(*(p[i] - p[j])))

        _, exact = exact_tour(n, distance)
        _, found = ortools_tour(n, distance, 1.0)
        assert found == pytest.approx(exact, rel=1e-6)


def test_router_caches_by_site_set():
    spots = {"BASE": (0, 0), "a": (0, 1000), "b": (1000, 1000), "c": (1000, 0)}

    def distance(x: str, y: str) -> float:
        return float(np.hypot(spots[x][0] - spots[y][0], spots[x][1] - spots[y][1]))

    router = Router(distance, "BASE", 1.0)
    assert router.tour(["a", "b", "c"])[1] == pytest.approx(4000)
    router.tour(["c", "b", "a"])
    assert router.solver_calls == 1
    assert router.tour([]) == ((), 0.0)


# Economics


CFG = load_yaml(ROOT / "config" / "decision" / "economics.yaml")


def _distance(a: str, b: str) -> float:
    spots = {"MAINT-BASE": (0, 0), "W1": (1000, 0), "W2": (0, 1000)}
    return float(np.hypot(spots[a][0] - spots[b][0], spots[a][1] - spots[b][1]))


def _tour(sites):
    stops = ["MAINT-BASE", *sorted(set(sites)), "MAINT-BASE"]
    return tuple(sorted(set(sites))), sum(_distance(a, b) for a, b in itertools.pairwise(stops))


def test_fixed_rounds_visit_every_site_each_cycle_and_charge_deferral():
    well = Asset("W1", "well", "W1", "PAD", flow_mcf_per_day=100.0)
    cfg = {
        **CFG,
        "horizon_days": 60,
        "inspection": {**CFG["inspection"], "finds_physical_fault": 1.0},
    }
    fault = Fault(well, physical=True, onset_h=0.0, alarm_h=None, localized=True)
    totals = simulate(
        "FIXED",
        [fault],
        [],
        ["W1", "W2"],
        cfg,
        _distance,
        _tour,
        "MAINT-BASE",
        np.random.default_rng(1),
    )
    assert totals.site_visits == 2 * 2  # two sites, a round every 30 days
    assert totals.physical_repaired == 1
    # Found on day 0 at midday and repaired a day later: 36 hours of 20% deferral of 100 Mcf a day.
    assert totals.deferred_mcf == pytest.approx(100 * 0.2 * 36 / 24)
    result = costs(totals, cfg)
    assert result["total"] == pytest.approx(
        result["travel"] + result["labor"] + result["deferred_production"]
    )


def test_risk_based_dispatches_on_alarms_and_counts_wasted_trips():
    cfg = {**CFG, "horizon_days": 10}
    false_alarm = Job(ready_h=30.0, site="W2", kind="FALSE_ALARM")
    totals = simulate(
        "RISK_BASED",
        [],
        [false_alarm],
        ["W1", "W2"],
        cfg,
        _distance,
        _tour,
        "MAINT-BASE",
        np.random.default_rng(1),
    )
    assert totals.alarm_trips == 1 and totals.trips_finding_nothing == 1
    fixed = simulate(
        "FIXED",
        [],
        [false_alarm],
        ["W1", "W2"],
        cfg,
        _distance,
        _tour,
        "MAINT-BASE",
        np.random.default_rng(1),
    )
    assert fixed.alarm_trips == 0


def test_strategies_see_the_same_faults():
    well = Asset("W1", "well", "W1", "PAD", flow_mcf_per_day=100.0)
    fault = Fault(well, physical=True, onset_h=5.0, alarm_h=6.0, localized=True)
    cfg = {**CFG, "horizon_days": 30}
    for strategy in ("FIXED", "RISK_BASED", "ROUTE_OPTIMIZED"):
        jobs = [Job(ready_h=6.0, site="W1", kind="ALARM")]
        simulate(
            strategy,
            [fault],
            jobs,
            ["W1", "W2"],
            cfg,
            _distance,
            _tour,
            "MAINT-BASE",
            np.random.default_rng(3),
        )
    assert fault.repaired_h is None  # simulate works on copies


def test_detector_stats_come_from_gate5():
    from pipelines.decision.economics import detector_stats

    stats = detector_stats(ROOT, CFG)
    assert isinstance(stats, DetectorStats)
    assert stats.detect_share["DERATE"] == pytest.approx(14 / 16)
    assert stats.detect_share["RESTRICTION"] == pytest.approx(9 / 16)
    assert stats.detect_share["SENSOR"] == pytest.approx(10 / 48)
