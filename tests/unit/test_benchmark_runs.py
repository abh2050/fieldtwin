"""The AETHER benchmark design: no leakage across splits, truth kept apart, and Gate 4 left alone."""

from __future__ import annotations

import numpy as np
import pytest

from packages.scenario_engine.benchmark_runs import (
    BenchmarkCase,
    CaseRefused,
    _check_envelope,
    _config_for,
    all_cases,
    class_name,
    fault_onset_s,
    load_design,
    sensor_tags,
    simulate_case,
)
from packages.scenario_engine.field_simulation import default_setup

CASES = all_cases()
BY_ID = {c.case_id: c for c in CASES}


def _first(category: str, split: str = "train") -> BenchmarkCase:
    return next(c for c in CASES if c.category == category and c.split == split)


def test_design_is_fixed_by_configuration_alone():
    assert [c.parameter_sha256() for c in all_cases()] == [c.parameter_sha256() for c in CASES]


def test_every_seed_and_parameter_set_is_unique_across_splits():
    assert len({c.seed for c in CASES}) == len(CASES)
    assert len({c.parameter_sha256() for c in CASES}) == len(CASES)


def test_split_sizes_match_the_design():
    counts = {}
    for case in CASES:
        counts[case.split] = counts.get(case.split, 0) + 1
    assert counts == {"train": 96, "validation": 32, "test": 32, "held_out": 112}


def test_all_required_variation_is_present():
    design = load_design()
    train = [c for c in CASES if c.split == "train"]
    assert {c.category for c in train} == set(design["categories"])
    assert len({c.well_multipliers for c in train}) == len(train)
    assert len({c.noise_multiplier for c in train}) > 1
    assert len({fault_onset_s(c) for c in train if fault_onset_s(c)}) > 1
    assert len({c.unit_capacity for c in train}) > 1
    assert all(len(c.setpoint_steps) >= 2 for c in train)  # Normal operating variation.


def test_held_out_regimes_lie_outside_training_ranges():
    train = [c for c in CASES if c.split in ("train", "validation", "test")]
    ranges = load_design()["regime"]
    assert all(
        ranges["severity"][0] <= f.max_severity <= ranges["severity"][1]
        for c in train
        for f in c.physical_faults
        if f.max_severity
    )
    for case in CASES:
        if case.regime == "severity_high":
            assert all(
                f.max_severity > ranges["severity"][1]
                for f in case.physical_faults
                if f.max_severity
            )
        if case.regime == "severity_low":
            assert all(
                f.max_severity < ranges["severity"][0]
                for f in case.physical_faults
                if f.max_severity
            )
        if case.regime == "noise_high":
            assert case.noise_multiplier > ranges["noise_multiplier"][1]
        if case.regime == "deliverability_outside":
            assert all(
                not ranges["well_multiplier"][0] <= m <= ranges["well_multiplier"][1]
                for _, m in case.well_multipliers
            )
        if case.regime == "compressor_outside":
            # Base setpoints lie outside the range, though a 2% step can reach just inside its edge.
            steps = [s for _, s in case.setpoint_steps]
            assert (
                case.units_offline
                and not ranges["setpoint_pa_abs"][0]
                <= np.median(steps)
                <= ranges["setpoint_pa_abs"][1]
            )


def test_unseen_assets_never_appear_in_training():
    train_assets = {f.asset_id for c in CASES if c.split == "train" for f in c.physical_faults}
    train_tags = {f.tag for c in CASES if c.split == "train" for f in c.sensor_faults} | {
        c.stuck_tag for c in CASES if c.split == "train" and c.stuck_tag
    }
    regime = [c for c in CASES if c.regime == "unseen_assets"]
    assert {f.asset_id for c in regime for f in c.physical_faults}.isdisjoint(train_assets)
    assert (
        {f.tag for c in regime for f in c.sensor_faults}
        | {c.stuck_tag for c in regime if c.stuck_tag}
    ).isdisjoint(train_tags)


def test_held_out_onsets_lie_outside_the_training_window():
    low, high = load_design()["regime"]["onset_days"]
    for case in CASES:
        if case.regime == "onset_outside" and fault_onset_s(case):
            assert not low <= fault_onset_s(case) / 86400 <= high


def test_telemetry_holds_sensor_values_only():
    run = simulate_case(_first("RESTRICTION"))
    assert list(run.telemetry.columns) == ["offset_s", *sensor_tags()]
    assert not [c for c in run.telemetry.columns if "truth" in c or "severity" in c or "onset" in c]
    assert {"y", "planned_active", "dropout_active"} <= set(run.labels.columns)


def test_labels_follow_the_declared_onset():
    case = _first("DERATE")
    labels = simulate_case(case).labels
    onset = fault_onset_s(case)
    assert labels.loc[labels["offset_s"] < onset, "y"].eq(0).all()
    assert labels.loc[labels["offset_s"] >= onset, "y"].eq(load_design()["classes"]["DERATE"]).all()


@pytest.mark.parametrize("category", ["NORMAL", "PLANNED", "COMM"])
def test_operations_and_dropouts_are_not_labeled_anomalies(category):
    case = _first(category)
    assert class_name(case) == "NORMAL" and simulate_case(case).labels["y"].eq(0).all()


def test_stuck_sensor_holds_its_last_value_and_others_keep_moving():
    case = _first("SENSOR_STUCK")
    telemetry = simulate_case(case).telemetry
    after = telemetry[telemetry["offset_s"] >= case.stuck_onset_s]
    assert after[case.stuck_tag].nunique() == 1
    assert after["MANIFOLD.PT"].nunique() > 1


def test_sensor_fault_changes_only_its_instrument():
    case = _first("SENSOR_BIAS")
    clean = BenchmarkCase(**{**case.__dict__, "sensor_faults": ()})
    faulted, baseline = simulate_case(case).telemetry, simulate_case(clean).telemetry
    tag = case.sensor_faults[0].tag
    others = [t for t in sensor_tags() if t != tag]
    assert np.array_equal(faulted[others].to_numpy(), baseline[others].to_numpy(), equal_nan=True)
    assert not np.array_equal(faulted[tag].to_numpy(), baseline[tag].to_numpy())


def test_dropout_gives_missing_values_not_zeros():
    case = _first("COMM")
    run = simulate_case(case)
    active = run.labels["dropout_active"].to_numpy()
    assert active.any() and run.telemetry.loc[active].isna().any().any()


def test_same_case_gives_the_same_telemetry():
    case = _first("NORMAL")
    assert simulate_case(case).telemetry.equals(simulate_case(case).telemetry)


def test_a_state_outside_the_envelope_is_refused():
    case = _first("NORMAL")
    from packages.scenario_engine.field_simulation import _truth_frame
    from packages.scenario_engine.network_solver import NetworkModel

    config = _config_for(case, 1.6e6)
    truth, _ = _truth_frame(NetworkModel(config, default_setup()[1]), case, np.array([0, 300]))  # type: ignore[arg-type]
    _check_envelope(case, truth, config)
    truth["truth_max_mach"] = 0.9
    with pytest.raises(CaseRefused):
        _check_envelope(case, truth, config)


def test_benchmark_doesnt_change_the_default_setup():
    config = default_setup()[0]
    _config_for(_first("NORMAL"), 1.5e6)
    assert config.compression.suction_setpoint_pa_abs == 1.6e6
    assert config.compression.units[0].capacity_sm3_per_s == 2.10
