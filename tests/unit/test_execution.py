"""The process guard tells solver nonconvergence, infeasible states, hangs, and crashes apart."""

from __future__ import annotations

import io
import json

import pytest

from packages.scenario_engine.execution import Outcome, run_with_timeout

MODULE = "packages.scenario_engine.execution:"


def test_successful_run_returns_its_result():
    report = run_with_timeout(
        MODULE + "gate4_scenario", {"scenario_id": "AETHER-NET-NORMAL"}, timeout_s=120, label="ok"
    )
    assert report.outcome is Outcome.OK
    assert (
        report.result["sha256"]
        == "80caededec3c1eab5a3ab75dba272728ea1b0b6760ee5abb14c51c9b2cc634d1"
    )
    assert report.result["max_newton_iterations"] <= 80


@pytest.mark.parametrize(
    ("target", "outcome"),
    [
        ("forced_nonconvergence", Outcome.SOLVER_NONCONVERGENCE),
        ("forced_infeasible", Outcome.INFEASIBLE_STATE),
        ("forced_crash", Outcome.CRASH),
    ],
)
def test_failures_are_classified(target, outcome):
    report = run_with_timeout(MODULE + target, {}, timeout_s=120, label=target)
    assert report.outcome is outcome and report.result is None and report.detail


def test_a_hang_is_killed_and_its_stack_is_captured():
    report = run_with_timeout(MODULE + "forced_hang", {}, timeout_s=3, label="hang")
    assert report.outcome is Outcome.EXECUTION_TIMEOUT
    assert report.elapsed_s < 30
    assert report.stack and "forced_hang" in report.stack


def test_timeout_is_not_reported_as_nonconvergence():
    assert Outcome.EXECUTION_TIMEOUT is not Outcome.SOLVER_NONCONVERGENCE
    assert (
        run_with_timeout(MODULE + "forced_hang", {}, timeout_s=2, label="h").outcome
        is not Outcome.SOLVER_NONCONVERGENCE
    )


def test_progress_is_logged_as_structured_lines():
    stream = io.StringIO()
    run_with_timeout(MODULE + "forced_crash", {}, timeout_s=60, label="logged", log=stream)
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [e["event"] for e in events] == ["start", "finish"]
    assert events[1]["outcome"] == "CRASH" and events[0]["label"] == "logged"


def test_solver_iterations_are_limited_in_configuration():
    from packages.scenario_engine.field_simulation import default_setup

    solver = default_setup()[0].solver
    assert 0 < solver.max_iterations <= 200 and 0 < solver.max_active_set_passes <= 50
