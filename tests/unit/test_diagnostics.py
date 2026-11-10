"""D1 development tests. Cases used here are generated from the development split's own definition."""

from __future__ import annotations

import ast
import json
import shutil
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
from pipelines.diagnostics.cases import FinalSplitLocked, build_case, check_freeze, prereg, simulate
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


def test_final_splits_are_locked_without_a_committed_freeze_record(tmp_path):
    (tmp_path / "config" / "diagnostics").mkdir(parents=True)
    shutil.copy(
        ROOT / "config" / "diagnostics" / "d1_preregistration.yaml",
        tmp_path / "config" / "diagnostics",
    )
    with pytest.raises(FinalSplitLocked, match="isn't frozen"):
        check_freeze(tmp_path)
    (tmp_path / "config" / "diagnostics" / "d1_freeze.yaml").write_text(
        yaml.safe_dump({"preregistration_sha256": "x"})
    )
    with pytest.raises(FinalSplitLocked):
        check_freeze(tmp_path)


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
