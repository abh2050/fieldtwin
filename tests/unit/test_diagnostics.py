"""D1 development tests. Cases used here are generated from the development split's own definition."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import yaml

from packages.diagnostics.baselines import b1_residual
from packages.diagnostics.diagnose import (
    Action,
    MethodConfig,
    diagnose,
    load_method,
    measurement_menu,
    valid_actions,
)
from packages.diagnostics.forward import Forward, calibrate_wells, sensors
from pipelines.diagnostics import cases, freeze
from pipelines.diagnostics.cases import build_case, prereg, simulate
from pipelines.diagnostics.freeze import FinalSplitLocked
from pipelines.diagnostics.port import MeasurementPort
from pipelines.diagnostics.scoring import brier, climatology, hypotheses

ROOT = Path(__file__).resolve().parents[2]
PREREG = prereg()
METHOD = load_method(ROOT / "config" / "diagnostics" / "d1_method.yaml")


# The truth boundary


FORBIDDEN = (
    "pipelines",
    "packages.scenario_engine.benchmark_runs",
    "packages.scenario_engine.field_simulation",
    "packages.scenario_engine.field_scenarios",
    "tests",
)


@pytest.mark.parametrize(
    "path", sorted((ROOT / "packages" / "diagnostics").glob("*.py")), ids=lambda p: p.name
)
def test_diagnosis_code_never_imports_the_generator_or_truth(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            assert not name.startswith(FORBIDDEN), f"{path.name} imports {name}"
    source = path.read_text()
    assert "/truth" not in source and "truth_" not in source and "true_state" not in source


def test_diagnosis_sensors_match_the_gate4_instruments():
    from packages.scenario_engine.field_simulation import build_sensors, default_setup

    config, graph, *_ = default_setup()
    gate4 = {
        s.tag: s.noise_std for s in build_sensors(config, graph) if not s.tag.endswith(".STATE")
    }
    mine = {s.tag: s.noise for s in sensors(config, graph)}
    assert mine == gate4


# Generator


def test_cases_are_reproducible_and_seeds_are_disjoint_from_earlier_gates():
    a, b = build_case("development", 7), build_case("development", 7)
    assert a == b
    assert min(PREREG["generator"]["seed_base"].values()) >= 900000
    count = PREREG["generator"]["cases"]["calibration"]
    restricted = sum(build_case("calibration", i).category == "RESTRICTION" for i in range(count))
    assert restricted == round(PREREG["generator"]["restriction_share"] * count)


def test_in_regime_cases_use_only_in_regime_pipes():
    pipes = {
        build_case("development", i).physical_faults[0].asset_id
        for i in range(60)
        if build_case("development", i).physical_faults
    }
    assert pipes <= set(PREREG["generator"]["in_regime"]["restriction_pipes"])
    assert not pipes & {"FL-A-06", "FL-B-03", "GS-TRUNK"}


# The freeze guard, on a temporary copy of the repository's protected files


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.invalid", "-c", "user.name=test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def frozen_repo(tmp_path):
    """A repository whose freeze record was committed and merged: the approved state."""
    for name in freeze.protected_files(ROOT):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "method")
    method = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    freeze.write_record(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "freeze")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path, method


def _merge(repo: Path) -> None:
    """Commit everything and move origin/main to it, as if the change had been reviewed and merged."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")


def test_the_approved_freeze_unlocks_the_final_splits(frozen_repo):
    repo, method = frozen_repo
    record = freeze.check_freeze(repo)
    assert record["method_commit"] == method
    assert set(record["protected_files"]) >= {
        "config/diagnostics/d1_method.yaml",
        "config/diagnostics/d1_preregistration.yaml",
        "packages/diagnostics/diagnose.py",
        "packages/diagnostics/forward.py",
        "pipelines/diagnostics/scoring.py",
        "pipelines/diagnostics/port.py",
        "pipelines/diagnostics/cases.py",
        "packages/scenario_engine/network_solver.py",
        "config/facility/aether_network.yaml",
        "uv.lock",
    }


def test_no_freeze_record_is_locked(tmp_path):
    with pytest.raises(FinalSplitLocked, match="isn't frozen"):
        freeze.check_freeze(tmp_path)


def test_an_unmerged_freeze_record_unlocks_nothing(frozen_repo):
    repo, method = frozen_repo
    _git(repo, "update-ref", "refs/remotes/origin/main", method)
    with pytest.raises(FinalSplitLocked, match="hasn't been reviewed and merged"):
        freeze.check_freeze(repo)


@pytest.mark.parametrize(
    "name",
    [
        "config/diagnostics/d1_method.yaml",
        "packages/diagnostics/diagnose.py",
        "packages/diagnostics/forward.py",
        "pipelines/diagnostics/scoring.py",
        "pipelines/diagnostics/port.py",
        "config/diagnostics/d1_preregistration.yaml",
    ],
)
def test_changing_a_protected_file_locks_the_final_splits(frozen_repo, name):
    repo, _ = frozen_repo
    with open(repo / name, "a") as handle:
        handle.write("\n# changed after the freeze\n")
    with pytest.raises(FinalSplitLocked, match="uncommitted"):
        freeze.check_freeze(repo)
    _merge(repo)
    with pytest.raises(
        FinalSplitLocked, match="changed since the freeze|different preregistration"
    ):
        freeze.check_freeze(repo)


def test_editing_the_freeze_record_locks_the_final_splits(frozen_repo):
    repo, _ = frozen_repo
    path = repo / freeze.RECORD
    path.write_text(path.read_text().replace("date: ", "date: 1999-01-01 # ", 1))
    with pytest.raises(FinalSplitLocked, match="uncommitted"):
        freeze.check_freeze(repo)
    _merge(repo)
    with pytest.raises(FinalSplitLocked, match="edited by hand"):
        freeze.check_freeze(repo)


def test_a_record_pointing_at_another_commit_is_refused(frozen_repo):
    repo, _ = frozen_repo
    path = repo / freeze.RECORD
    record = yaml.safe_load(path.read_text())
    (repo / "packages/diagnostics/diagnose.py").write_text("# a different method\n")
    _merge(repo)
    other = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    (repo / "packages/diagnostics/diagnose.py").write_text(
        (ROOT / "packages/diagnostics/diagnose.py").read_text()
    )
    record["method_commit"] = other
    record["record_sha256"] = freeze.record_digest(record)
    path.write_text(yaml.safe_dump(record, sort_keys=False))
    _merge(repo)
    with pytest.raises(FinalSplitLocked, match="at the recorded method commit"):
        freeze.check_freeze(repo)


def test_generation_of_a_final_split_goes_through_the_guard(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cases,
        "check_freeze",
        lambda root: calls.append(root) or (_ for _ in ()).throw(FinalSplitLocked("locked")),
    )
    with pytest.raises(FinalSplitLocked):
        cases.generate("final_in_regime")
    with pytest.raises(FinalSplitLocked):
        cases.generate("final_held_out")
    assert len(calls) == 2


# Forward model and diagnosis on one generated development case


@pytest.fixture(scope="module")
def case():
    built = build_case("development", 5)
    telemetry, truth = simulate(built)
    return telemetry, {"case_id": built.case_id, "planned_operations": []}, truth


def test_well_calibration_recovers_deliverability(case):
    telemetry, _, truth = case
    base = telemetry[telemetry["offset_s"] < 21600]
    design = Forward({}, 1.6e6).design
    found = calibrate_wells(
        design,
        {w.id: base[f"{w.id}.FT"].mean() for w in design.wells},
        {w.id: base[f"{w.id}.PT-WH"].mean() for w in design.wells},
    )
    for well, multiplier in truth["true_state"]["well_multipliers"].items():
        assert found[well] == pytest.approx(multiplier, abs=0.005)


def test_diagnosis_localizes_explains_and_recommends(case):
    telemetry, calendar, truth = case
    diagnosis, diagnoser = diagnose(telemetry, calendar, PREREG, METHOD)
    assert sum(diagnosis.probabilities.values()) == pytest.approx(1.0)
    assert set(diagnosis.probabilities) == set(hypotheses(PREREG))
    assert diagnosis.ranking[0] == truth["faulted_pipe"]
    assert (
        diagnosis.severity["p2_5"]
        <= diagnosis.severity["p10"]
        <= diagnosis.severity["p90"]
        <= diagnosis.severity["p97_5"]
    )
    assert diagnosis.impact["p10"] <= diagnosis.impact["point"] <= diagnosis.impact["p90"]
    top = diagnosis.evidence[diagnosis.ranking[0]]
    assert top["for"] and top["against"] in diagnosis.probabilities
    rec = diagnosis.recommendation
    assert rec is not None and Action(rec["kind"], rec["target"]) in valid_actions(
        measurement_menu(PREREG), frozenset()
    )
    reading = MeasurementPort(truth, PREREG).read(
        Action(rec["kind"], rec["target"]), diagnoser.sensors
    )
    assert isinstance(reading, np.ndarray) and reading.ndim == 1
    after = diagnoser.update(Action(rec["kind"], rec["target"]), reading)
    assert after.recommendation is None and sum(after.probabilities.values()) == pytest.approx(1.0)


def test_no_restriction_case_ranks_none_first():
    built = next(
        build_case("development", i)
        for i in range(50)
        if build_case("development", i).category == "NONE"
    )
    telemetry, _ = simulate(built)
    diagnosis, _ = diagnose(telemetry, {"planned_operations": []}, PREREG, METHOD, recommend=False)
    assert diagnosis.ranking[0] == "NONE"
    # B1 uses nominal wells, so it may flag a pipe here; it must still rank every hypothesis.
    assert set(b1_residual(telemetry, PREREG)["ranking"]) == set(hypotheses(PREREG))


# Actions and scoring


def test_the_action_set_has_55_actions_and_respects_shut_ins():
    menu = measurement_menu(PREREG)
    assert len(valid_actions(menu, frozenset())) == 55
    reduced = valid_actions(menu, frozenset({"A-01"}))
    assert len(reduced) == 53
    assert (
        Action("PORTABLE_DP", "FL-A-01") in reduced and Action("WELL_TEST", "A-01") not in reduced
    )


def test_climatology_is_the_generator_frequency():
    clim = climatology(PREREG)
    assert sum(clim.values()) == pytest.approx(1.0)
    assert clim["NONE"] == pytest.approx(0.15)
    assert clim["GS-TRUNK"] == 0.0 and clim["GS-A"] == pytest.approx(0.85 / 12)
    labels = hypotheses(PREREG)
    assert brier({"GS-A": 1.0}, "GS-A", labels) == 0.0
    assert brier({"GS-A": 1.0}, "NONE", labels) == 2.0


def test_method_config_is_the_frozen_file():
    data = yaml.safe_load((ROOT / "config" / "diagnostics" / "d1_method.yaml").read_text())
    assert MethodConfig(**data) == METHOD and METHOD.temperature == 3.0
    assert json.dumps(data, sort_keys=True)


def test_degraded_inputs_still_give_a_valid_diagnosis(case):
    """Code paths the held-out degraded-operations regime needs, which no development calendar exercises:
    a declared shut-in and a pad's telemetry lost. This checks the diagnosis completes and stays well
    formed, not that it is accurate."""
    telemetry, _, _ = case
    damaged = telemetry.copy()
    lost = damaged["offset_s"] > 259200 - 10 * 3600
    for column in [c for c in damaged.columns if c.startswith(("B-", "HDR-B"))]:
        damaged.loc[lost, column] = np.nan
    calendar = {
        "planned_operations": [
            {"kind": "SHUT_IN_WELL", "asset_id": "A-02", "start_s": 0, "end_s": 300000}
        ]
    }
    diagnosis, diagnoser = diagnose(damaged, calendar, PREREG, METHOD)
    assert sum(diagnosis.probabilities.values()) == pytest.approx(1.0)
    assert "A-02" in diagnoser.shut_in
    assert not any(s.tag.startswith(("B-", "HDR-B")) for s in diagnoser.sensors)
    rec = diagnosis.recommendation
    assert rec is not None and not (
        rec["kind"] in ("WELL_TEST", "SHUT_IN_TEST") and rec["target"] == "A-02"
    )


# Degraded operations and the final acceptance rules (both fixed before any final case existed)


def test_degraded_operations_regime_creates_shut_ins_and_a_dropout():
    """Built from the development split's seeds, so no final case is drawn."""
    case = build_case("development", 3, regime="degraded_operations")
    shut = case.planned_operations
    assert 1 <= len(shut) <= 2 and all(op.kind == "SHUT_IN_WELL" for op in shut)
    diagnosis_offset = PREREG["generator"]["duration_s"] - PREREG["generator"]["interval_s"]
    for op in shut:
        assert (
            diagnosis_offset - 24 * 3600 <= op.start_s <= diagnosis_offset - 4 * 3600
            and op.active(diagnosis_offset)
        )
    [drop] = case.communication_faults
    assert drop.group in ("PAD-A", "PAD-B")
    assert 6 * 3600 - 300 <= PREREG["generator"]["duration_s"] - drop.onset_s <= 18 * 3600
    telemetry, truth = simulate(case)
    lost = [c for c in telemetry.columns if c.startswith(drop.group[-1] + "-")]
    assert telemetry.loc[telemetry["offset_s"] >= drop.onset_s, lost].isna().all().all()
    assert set(truth["true_state"]["shut_in_wells"]) == {op.asset_id for op in shut}
    assert cases.calendar(case)["planned_operations"]


def test_other_regimes_and_splits_draw_no_degradation():
    for regime in ("in_regime", "noise_high", "unseen_pipes"):
        case = build_case("development", 3, regime=regime)
        assert not case.planned_operations and not case.communication_faults


def _metrics(**overrides):
    base = {
        "primary_cases": 120,
        "no_restriction_cases": 20,
        "impact_relative_error_cases": 60,
        "top1": 0.9,
        "top1_minus_b1_interval": [0.1, 0.3],
        "top3": 0.95,
        "specificity": 0.9,
        "miss_rate": 0.0,
        "joint_success_rate": 0.8,
        "impact_within_tolerance": 0.9,
        "impact_median_relative_error": 0.05,
        "brier_skill_score_vs_climatology": 0.8,
        "expected_calibration_error": 0.05,
        "coverage_80": {"severity": 0.8, "impact": 0.8},
        "coverage_95": {"severity": 0.95, "impact": 0.95},
        "measurement_entropy_reduction": 0.3,
        "measurement_top1_gain": 0.1,
        "measurement_top1_gain_interval": [0.02, 0.2],
        "measurement_against_random_interval": [0.01, 0.05],
    }
    return {**base, **overrides}


def test_acceptance_rules_follow_the_preregistration():
    from pipelines.diagnostics.final import held_out_lines, in_regime_lines, outcome

    lines, supported = in_regime_lines(_metrics(), PREREG)
    assert supported and all(line["status"] == "PASS" for line in lines)
    assert outcome(lines, supported, None) == {"outcome": "PENDING_HELD_OUT"}
    held = held_out_lines({"noise_high": _metrics(top1=0.5)}, _metrics(primary_cases=150), PREREG)
    assert outcome(lines, supported, held)["outcome"] == "MET_IN_REGIME_ONLY"
    held_ok = held_out_lines({"noise_high": _metrics()}, _metrics(primary_cases=150), PREREG)
    assert outcome(lines, supported, held_ok) == {"outcome": "MET"}
    failing, ok = in_regime_lines(
        _metrics(measurement_top1_gain=0.0, measurement_top1_gain_interval=[0.0, 0.0]), PREREG
    )
    assert outcome(failing, ok, held_ok)["failed_in_regime_lines"] == ["measurement_top1_gain"]
    short, short_ok = in_regime_lines(_metrics(primary_cases=50), PREREG)
    assert not short_ok and outcome(short, short_ok, held_ok)["outcome"] == "INCONCLUSIVE"
    sparse = held_out_lines(
        {"noise_high": _metrics(primary_cases=10)}, _metrics(primary_cases=150), PREREG
    )
    assert any(line["status"] == "INCONCLUSIVE" for line in sparse)
    assert outcome(lines, supported, sparse)["outcome"] == "MET_IN_REGIME_ONLY"
    few_big, few_ok = in_regime_lines(_metrics(impact_relative_error_cases=10), PREREG)
    assert (
        next(line for line in few_big if line["line"] == "impact_median_relative_error")["status"]
        == "INCONCLUSIVE"
    )
    assert outcome(few_big, few_ok, held_ok)["outcome"] == "NOT_MET"


def test_the_final_runner_refuses_without_an_approved_freeze(monkeypatch):
    from pipelines.diagnostics import final

    monkeypatch.setattr(
        final, "check_freeze", lambda root: (_ for _ in ()).throw(FinalSplitLocked("locked"))
    )
    with pytest.raises(FinalSplitLocked):
        final.run_split("final_in_regime")
    with pytest.raises(ValueError):
        final.run_split("development")
