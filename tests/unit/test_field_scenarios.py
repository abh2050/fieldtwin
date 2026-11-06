"""The six scenarios: separation of fault kinds, telemetry, attribution, and consequences."""

from __future__ import annotations

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from packages.domain.events import EventDomain
from packages.scenario_engine.field_events import field_events
from packages.scenario_engine.field_invariants import (
    FieldInvariantViolation,
    check_field_run,
    junction_balances,
    require_field_run,
)
from packages.scenario_engine.field_scenarios import (
    CATALOG_PATH,
    Category,
    FieldCatalog,
    FieldScenario,
)
from packages.scenario_engine.field_simulation import (
    BAD_COMM,
    FieldRun,
    default_setup,
    simulate_by_id,
    simulate_field,
)
from packages.scenario_engine.propagation import PROPAGATION_CASES, compare
from tests.conftest import REPO_ROOT

CONFIG, GRAPH, MODEL, CATALOG, SENSORS = default_setup()
NORMAL = "AETHER-NET-NORMAL"
RESTRICTION = "AETHER-FAULT-001-NET"
DERATE = "AETHER-NET-COMPRESSOR-DERATE"
SENSOR = "AETHER-NET-SENSOR-DRIFT"
COMM = "AETHER-NET-COMM-DROPOUT"
PLANNED = "AETHER-NET-PLANNED-SHUTDOWN"
ALL = [NORMAL, RESTRICTION, DERATE, SENSOR, COMM, PLANNED]
TRUTH_ONLY = lambda frame: frame.drop(columns=["truth_fault_active"])  # noqa: E731


def run_of(scenario_id):
    return simulate_by_id(scenario_id)


def tag_rows(scenario_id, tag):
    frame = run_of(scenario_id).telemetry
    return frame[frame["tag"] == tag].reset_index(drop=True)


def test_catalog_holds_the_six_required_scenarios():
    assert sorted(s.scenario_id for s in CATALOG.scenarios) == sorted(ALL)
    categories = {s.scenario_id: s.category for s in CATALOG.scenarios}
    assert categories[NORMAL] is Category.NORMAL
    assert categories[RESTRICTION] is Category.PHYSICAL_FAULT
    assert categories[DERATE] is Category.PHYSICAL_FAULT
    assert categories[SENSOR] is Category.SENSOR_FAULT
    assert categories[COMM] is Category.COMMUNICATION_FAULT
    assert categories[PLANNED] is Category.PLANNED_OPERATION


@pytest.mark.parametrize("scenario_id", ALL)
def test_every_scenario_passes_every_declared_check(scenario_id):
    checks = check_field_run(run_of(scenario_id))
    assert [c.name for c in checks if not c.passed] == []
    assert len(checks) >= 16


@pytest.mark.parametrize("scenario_id", ALL)
def test_scenarios_are_deterministic(scenario_id):
    scenario = CATALOG.get(scenario_id)
    first, second = simulate_field(scenario), simulate_field(scenario)
    assert first.telemetry.equals(second.telemetry)
    assert first.truth.equals(second.truth)
    assert first.canonical_sha256() == second.canonical_sha256()


def test_sensor_and_communication_scenarios_do_not_change_the_physics():
    baseline = TRUTH_ONLY(run_of(NORMAL).truth)
    for scenario_id in (SENSOR, COMM):
        assert TRUTH_ONLY(run_of(scenario_id).truth).equals(baseline), scenario_id


def test_physical_scenarios_do_change_the_physics():
    baseline = run_of(NORMAL).truth["truth_total_flow"].to_numpy()
    for scenario_id in (RESTRICTION, DERATE, PLANNED):
        assert not np.array_equal(
            run_of(scenario_id).truth["truth_total_flow"].to_numpy(), baseline
        )


def test_sensor_fault_changes_only_the_faulted_instruments():
    normal = run_of(NORMAL).telemetry
    faulted = run_of(SENSOR).telemetry
    changed = set(normal.loc[normal["value"].to_numpy() != faulted["value"].to_numpy(), "tag"])
    assert changed == {"A-03.PT-WH", "GS-B.DPT-NET"}


def test_drift_grows_from_its_onset_and_leaves_truth_alone():
    fault = CATALOG.get(SENSOR).sensor_faults[0]
    gap = tag_rows(SENSOR, fault.tag)["value"] - tag_rows(NORMAL, fault.tag)["value"]
    offsets = tag_rows(NORMAL, fault.tag)["offset_s"]
    assert (gap[offsets < fault.onset_s].abs() < 1e-9).all()
    expected = 5000.0 * (offsets - fault.onset_s) / 86400.0
    after = offsets >= fault.onset_s
    assert np.allclose(gap[after], expected[after], atol=1e-6)


def test_bias_is_a_constant_step_at_onset():
    fault = CATALOG.get(SENSOR).sensor_faults[1]
    gap = tag_rows(SENSOR, fault.tag)["value"] - tag_rows(NORMAL, fault.tag)["value"]
    offsets = tag_rows(NORMAL, fault.tag)["offset_s"]
    assert (gap[offsets < fault.onset_s].abs() < 1e-9).all()
    assert np.allclose(gap[offsets >= fault.onset_s], 8000.0, atol=1e-6)


def test_undetected_sensor_fault_still_reports_good_quality():
    """A drifting transmitter doesn't know it is wrong. Only truth records the fault."""
    rows = tag_rows(SENSOR, "A-03.PT-WH")
    assert set(rows["quality"]) == {"GOOD"} and set(rows["sensor_status"]) == {"OK"}


def test_dropout_removes_only_the_right_readings_in_the_right_window():
    frame = run_of(COMM).telemetry
    lost = frame[frame["quality"] == BAD_COMM]
    assert lost["value"].isna().all()
    assert set(lost["sensor_status"]) == {"COMM_LOST"}
    pad_b = lost[lost["offset_s"].between(259200, 302399)]
    expected_assets = {f"B-0{i}" for i in range(1, 7)} | {"HDR-B", "GS-B"}
    assert set(pad_b["asset_id"]) == expected_assets
    unit = lost[lost["offset_s"].between(432000, 453599)]
    assert set(unit["asset_id"]) == {"C-02"}
    assert len(lost) == len(pad_b) + len(unit)


def test_physics_continues_during_a_dropout():
    truth = run_of(COMM).truth
    during = truth[truth["offset_s"].between(259200, 302399)]
    assert (during["truth_q_INFLOW:B-01"] > 0).all()


@pytest.mark.parametrize("scenario_id", [RESTRICTION, DERATE, SENSOR, COMM, PLANNED])
def test_nothing_happens_before_the_known_onset(scenario_id):
    onset = CATALOG.get(scenario_id).first_onset_s
    baseline, run = run_of(NORMAL), run_of(scenario_id)
    before = baseline.telemetry["offset_s"] < onset
    columns = ["tag", "value", "quality", "sensor_status", "equipment_state"]
    assert baseline.telemetry.loc[before, columns].equals(run.telemetry.loc[before, columns])


@pytest.mark.parametrize("scenario_id", [RESTRICTION, DERATE, PLANNED])
def test_physics_responds_at_the_declared_onset(scenario_id):
    onset = CATALOG.get(scenario_id).first_onset_s
    truth = run_of(scenario_id).truth
    baseline = run_of(NORMAL).truth["truth_total_flow"].iloc[0]
    assert truth.loc[truth["offset_s"] <= onset - 300, "truth_total_flow"].eq(baseline).all() or (
        (truth.loc[truth["offset_s"] <= onset - 300, "truth_total_flow"] - baseline).abs().max()
        < 1e-9
    )
    later = truth[truth["offset_s"] > onset]
    assert (later["truth_total_flow"] - baseline).abs().max() > 1e-6


def test_restriction_grows_then_holds():
    truth = run_of(RESTRICTION).truth
    severity = truth["truth_severity_GS-A"].to_numpy()
    assert (np.diff(severity) >= 0).all()
    assert severity.max() == 0.65
    assert severity[truth["offset_s"] <= 172800].max() == 0


def test_derate_reaches_the_capacity_limited_regime():
    truth = run_of(DERATE).truth
    assert set(truth["truth_regime"]) == {"SETPOINT_CONTROLLED", "CAPACITY_LIMITED"}
    limited = truth[truth["truth_regime"] == "CAPACITY_LIMITED"]
    assert (limited["truth_p_COMP-SUCTION"] > 1.6e6).all()
    assert limited["offset_s"].min() > 172800


def test_planned_shutdown_returns_to_normal_afterward():
    truth = run_of(PLANNED).truth
    baseline = run_of(NORMAL).truth["truth_total_flow"].iloc[0]
    during = truth[truth["offset_s"].between(259200, 302399)]
    assert (during["truth_q_GS-B"] == 0).all()
    assert (during["truth_state_C-04"] == "STOPPED").all()
    shut = truth[truth["offset_s"].between(432000, 475199)]
    assert (shut["truth_status_A-02"] == "SHUT_IN").all()
    assert abs(truth["truth_total_flow"].iloc[-1] - baseline) < 1e-9


def test_isolated_sensors_report_equipment_state():
    rows = tag_rows(PLANNED, "B-01.FT")
    window = rows[rows["offset_s"].between(259200, 302399)]
    assert set(window["equipment_state"]) == {"ISOLATED"}
    assert set(tag_rows(NORMAL, "B-01.FT")["equipment_state"]) == {"PRODUCING"}
    state = tag_rows(PLANNED, "C-04.STATE")
    assert set(state.loc[state["offset_s"].between(259200, 302399), "value"]) == {0.0}
    assert set(tag_rows(NORMAL, "C-04.STATE")["value"]) == {2.0}


# Telemetry


def test_required_measurements_are_all_present():
    positions = {s.measurement_definition_id for s in SENSORS}
    assert {
        "aether_well.tubing_head_pressure",
        "aether_gathering.manifold_pressure",
        "aether_gathering.network_segment_differential_pressure",
        "aether_well.gas_flow_rate",
        "aether_compression.operating_state",
    } <= positions
    columns = set(run_of(NORMAL).telemetry.columns)
    assert {
        "sensor_status",
        "equipment_state",
        "quality",
        "simulated_time",
        "unit",
        "reference",
        "sensor_position",
    } <= columns


def test_sensors_match_their_declared_measurement_definitions():
    reference = yaml.safe_load(
        (REPO_ROOT / "data_contracts/semantic_mappings/reference_data.yaml").read_text()
    )
    definitions = {
        m["id"]: m
        for key in (
            "aether_measurements",
            "aether_gathering_measurements",
            "aether_compression_measurements",
        )
        for m in reference[key]
    }
    units = {u["unit_id"]: u["physical_quantity"] for u in reference["units"]}
    for sensor in SENSORS:
        definition = definitions[sensor.measurement_definition_id]
        assert definition["unit"] == sensor.unit
        assert definition["reference"] == sensor.reference
        assert definition["quantity"] == sensor.quantity == units[sensor.unit]
        assert sensor.display_unit in units


def test_gauge_sensors_read_one_ambient_below_absolute():
    rows = tag_rows(NORMAL, "MANIFOLD.PT")
    truth = run_of(NORMAL).truth["truth_p_MANIFOLD"].to_numpy()
    assert (truth - rows["value"].to_numpy()).mean() == pytest.approx(90000.0, abs=200)


def test_differential_sensor_needs_no_ambient_and_matches_pressures():
    rows = tag_rows(NORMAL, "GS-A.DPT-NET")
    truth = run_of(NORMAL).truth
    expected = (truth["truth_p_HDR-A"] - truth["truth_p_MANIFOLD"]).to_numpy()
    assert (rows["value"].to_numpy() - expected).std() == pytest.approx(500.0, rel=0.1)
    assert abs((rows["value"].to_numpy() - expected).mean()) < 100


def test_readings_stay_mutually_coherent_within_noise():
    """Upstream minus downstream readings must equal the differential reading, within noise."""
    a = tag_rows(RESTRICTION, "HDR-A.PT-NET")["value"].to_numpy()
    b = tag_rows(RESTRICTION, "MANIFOLD.PT")["value"].to_numpy()
    d = tag_rows(RESTRICTION, "GS-A.DPT-NET")["value"].to_numpy()
    gap = a - b - d
    assert gap.std() == pytest.approx(np.sqrt(2000.0**2 * 2 + 500.0**2), rel=0.1)
    assert abs(gap.mean()) < 300


def test_simulated_clock_cannot_be_mistaken_for_real_operations():
    assert run_of(NORMAL).telemetry["simulated_time"].iloc[0].startswith("2040-01-01")


@pytest.mark.parametrize("scenario_id", ALL)
def test_every_row_is_attributed_and_versioned(scenario_id):
    run = run_of(scenario_id)
    frame = run.telemetry
    assert set(frame["provenance_class"]) == {"SYNTHETIC"}
    assert set(frame["scenario_id"]) == {scenario_id}
    assert set(frame["scenario_run_id"]) == {run.run_id}
    assert set(frame["simulator_version"]) == {CONFIG.network.version}
    assert set(frame["parameter_set_sha256"]) == {run.parameter_set_sha256}
    assert set(frame["tag"]) == {s.tag for s in SENSORS}


def test_parameter_set_differs_between_scenarios():
    assert len({run_of(s).parameter_set_sha256 for s in ALL}) == 6


def test_telemetry_excludes_simulator_truth():
    assert not [c for c in run_of(RESTRICTION).telemetry.columns if c.startswith("truth_")]


def test_noise_streams_are_tied_to_tags():
    a = tag_rows(NORMAL, "A-01.FT")["value"].to_numpy()
    b = tag_rows(NORMAL, "A-02.FT")["value"].to_numpy()
    assert np.corrcoef(a, b)[0, 1] < 0.2


# Checks catch corruption


def corrupted(column, factor):
    run = run_of(RESTRICTION)
    truth = run.truth.copy()
    truth[column] = truth[column] * factor
    return FieldRun(
        run.scenario,
        truth,
        run.telemetry,
        run.parameter_set_sha256,
        run.simulator_name,
        run.simulator_version,
        run.seed,
    )


def test_broken_mass_balance_is_caught_and_the_run_refused():
    with pytest.raises(FieldInvariantViolation, match="junction_mass_balance"):
        require_field_run(corrupted("truth_q_GS-A", 1.001))


def test_wrong_pressure_is_caught():
    names = {c.name for c in check_field_run(corrupted("truth_p_WH:A-03", 1.01)) if not c.passed}
    assert "well_inflow_equation" in names


def test_junction_balances_are_small_everywhere():
    for scenario_id in ALL:
        assert max(np.abs(v).max() for v in junction_balances(run_of(scenario_id)).values()) < 1e-8


# Scenario contract


def scenario(**overrides):
    values = {
        "scenario_id": "X", "name": "x", "version": 1, "category": "NORMAL",
        "target_asset_id": "A-01", "affected_asset_id": "A-01", "description": "x",
    }  # fmt: skip
    return FieldScenario(**{**values, **overrides})


PHYSICAL = {
    "kind": "SEGMENT_RESTRICTION",
    "asset_id": "GS-A",
    "onset_s": 10,
    "full_s": 20,
    "max_severity": 0.5,
}
BIAS = {"kind": "BIAS", "tag": "A-03.PT-WH", "onset_s": 10, "magnitude": 1.0}
DROP = {"group": "PAD-B", "onset_s": 10, "end_s": 20}


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "SENSOR_FAULT", "sensor_faults": [BIAS], "physical_faults": [PHYSICAL]},
        {
            "category": "PHYSICAL_FAULT",
            "physical_faults": [PHYSICAL],
            "communication_faults": [DROP],
        },
        {
            "category": "COMMUNICATION_FAULT",
            "communication_faults": [DROP],
            "sensor_faults": [BIAS],
        },
        {"category": "NORMAL", "physical_faults": [PHYSICAL]},
        {"category": "PHYSICAL_FAULT"},
        {"category": "PHYSICAL_FAULT", "physical_faults": [{**PHYSICAL, "full_s": 5}]},
        {"category": "PHYSICAL_FAULT", "physical_faults": [{**PHYSICAL, "final_fraction": 0.5}]},
        {"category": "SENSOR_FAULT", "sensor_faults": [{"kind": "BIAS", "tag": "x", "onset_s": 1}]},
        {"category": "COMMUNICATION_FAULT", "communication_faults": [{**DROP, "end_s": 5}]},
        {"unexpected": 1},
    ],
)
def test_fault_kinds_cannot_be_mixed_and_invalid_scenarios_are_refused(overrides):
    with pytest.raises(ValidationError):
        scenario(**overrides)


def test_duplicate_scenario_ids_are_refused():
    data = yaml.safe_load(CATALOG_PATH.read_text())
    data["scenarios"].append(dict(data["scenarios"][0]))
    with pytest.raises(ValidationError):
        FieldCatalog.model_validate(data)


# Cross-domain


def test_no_field_configuration_or_output_refers_to_3w():
    for path in (
        "config/facility/aether_network.yaml",
        "config/scenarios/aether_field_scenarios.yaml",
    ):
        body = (REPO_ROOT / path).read_text().lower()
        assert "petrobras" not in body and "3w" not in body
    for scenario_id in ALL:
        run = run_of(scenario_id)
        assert not run.telemetry["tag"].str.contains("petrobras").any()
    for sensor in SENSORS:
        assert sensor.equipment_class_id.startswith("AETHER_")


@pytest.mark.parametrize("scenario_id", ALL)
def test_events_stay_in_the_synthetic_domain_with_known_onsets(scenario_id):
    run = run_of(scenario_id)
    events = field_events(run)
    assert len(events) == (
        len(run.scenario.physical_faults)
        + len(run.scenario.sensor_faults)
        + len(run.scenario.communication_faults)
        + len(run.scenario.planned_operations)
    )
    for event in events:
        assert event.domain is EventDomain.AETHER_SYNTHETIC
        assert event.telemetry_event_id is None
        assert event.evidence["basis"].startswith("Declared")


# Cross-asset consequences


@pytest.mark.parametrize("scenario_id", list(PROPAGATION_CASES))
def test_every_effect_predicted_from_topology_matches_the_coupled_solve(scenario_id):
    results = compare(scenario_id)
    assert len(results) >= 16
    assert [
        (r.effect.asset_id, r.effect.quantity, r.effect.direction, r.observed_direction)
        for r in results
        if not r.matches
    ] == []
    assert all(len(r.effect.why) > 10 for r in results)


def test_restriction_in_gs_a_reaches_the_other_pad_only_through_the_manifold():
    results = {(r.effect.asset_id, r.effect.quantity): r for r in compare(RESTRICTION)}
    assert results[("A-03", "Gas flow")].change < 0
    assert results[("B-03", "Gas flow")].change > 0
    assert results[("MANIFOLD", "Manifold pressure")].change < 0
    assert abs(results[("A-03", "Gas flow")].percent) > abs(results[("B-03", "Gas flow")].percent)


def test_derate_reaches_every_well():
    results = compare(DERATE)
    wells = [r for r in results if r.effect.quantity == "Gas flow"]
    assert len(wells) == 12 and all(r.change < 0 for r in wells)
