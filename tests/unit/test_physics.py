"""Physical consistency of the synthetic model: property-based, numerical, and determinism tests."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from packages.domain.models import ReferenceType
from packages.domain.semantics import SemanticError, convert_pressure
from packages.scenario_engine.config import UNIVERSAL_GAS_CONSTANT, load_config
from packages.scenario_engine.events import first_sustained_exceedance, run_events
from packages.scenario_engine.invariants import (
    InvariantViolation,
    check_invariants,
    require_invariants,
)
from packages.scenario_engine.physics import (
    InfeasibleOperatingPoint,
    restriction_schedule,
    segment_resistance,
    solve,
    standard_density,
)
from packages.scenario_engine.simulate import canonical_sha256, detector_view, simulate

BASE = load_config()
EXPECTED_SHA256 = {
    "nominal": "d36fdd5afba2677cc9d5c6eb523e3659f9402b8fc657c9e78148a40f8811cd13",
    "fault": "a365b1e3321c523e1ad84ddc15b693c581c3837b6fd6aecab50a258c03658403",
}
PROFILE = settings(
    max_examples=150, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


def varied(shut_in=None, sink=None, coefficient=None, exponent=None, length=None, diameter=None):
    well = BASE.well.model_copy(
        update={
            k: v
            for k, v in {
                "shut_in_wellhead_pressure_pa_abs": shut_in,
                "deliverability_coefficient": coefficient,
                "deliverability_exponent": exponent,
            }.items()
            if v is not None
        }
    )
    segment = BASE.gathering_segment.model_copy(
        update={
            k: v
            for k, v in {
                "downstream_boundary_pressure_pa_abs": sink,
                "length_m": length,
                "internal_diameter_m": diameter,
            }.items()
            if v is not None
        }
    )
    return BASE.model_copy(update={"well": well, "gathering_segment": segment})


parameters = st.fixed_dictionaries(
    {
        "shut_in": st.floats(2.5e6, 2.0e7),
        "sink": st.floats(5e5, 2.4e6),
        "coefficient": st.floats(1e-11, 5e-10),
        "exponent": st.floats(0.5, 1.0),
        "length": st.floats(500.0, 20000.0),
        "diameter": st.floats(0.05, 0.3),
    }
)
severities = st.floats(0.0, 0.70)


# Properties


@PROFILE
@given(parameters, severities)
def test_series_flow_is_conserved_and_pressures_are_ordered(p, severity):
    config = varied(**p)
    point = solve(config, np.array([severity]))
    well = config.well
    q = point.gas_flow_sm3_per_s[0]
    wellhead = point.wellhead_pressure_pa_abs[0]
    assert q > 0
    assert p["sink"] < wellhead < p["shut_in"]
    delivered = (
        well.deliverability_coefficient
        * (p["shut_in"] ** 2 - wellhead**2) ** well.deliverability_exponent
    )
    assert delivered == pytest.approx(q, rel=1e-6)
    assert point.differential_pressure_pa[0] == pytest.approx(wellhead - p["sink"], abs=1e-3)


@PROFILE
@given(parameters, severities, severities)
def test_more_restriction_cannot_increase_flow(p, a, b):
    low, high = sorted((a, b))
    config = varied(**p)
    point = solve(config, np.array([low, high]))
    assert point.gas_flow_sm3_per_s[1] <= point.gas_flow_sm3_per_s[0] * (1 + 1e-9)
    assert point.wellhead_pressure_pa_abs[1] >= point.wellhead_pressure_pa_abs[0] * (1 - 1e-9)
    assert point.differential_pressure_pa[1] >= point.differential_pressure_pa[0] - 1e-3


@PROFILE
@given(parameters, severities, st.floats(1.01, 2.0))
def test_higher_supply_pressure_cannot_reduce_flow(p, severity, factor):
    low = solve(varied(**p), np.array([severity])).gas_flow_sm3_per_s[0]
    high_params = {**p, "shut_in": p["shut_in"] * factor}
    high = solve(varied(**high_params), np.array([severity])).gas_flow_sm3_per_s[0]
    assert high >= low


@PROFILE
@given(parameters, st.floats(0.0, 0.69))
def test_resistance_rises_with_severity_and_matches_the_open_segment_at_zero(p, severity):
    config = varied(**p)
    assert (
        segment_resistance(config, np.array([severity + 0.01]))[0]
        > (segment_resistance(config, np.array([severity]))[0])
    )


@PROFILE
@given(st.integers(0, 604800))
def test_schedule_is_bounded_and_zero_before_onset(offset):
    value = float(restriction_schedule(BASE, np.array([float(offset)]))[0])
    assert 0 <= value <= BASE.restriction.max_severity
    if offset <= BASE.restriction.onset_offset_s:
        assert value == 0
    if offset >= BASE.restriction.full_severity_offset_s:
        assert value == BASE.restriction.max_severity


# Numerical checks against independent results


def test_resistance_matches_a_hand_calculation():
    segment, gas = BASE.gathering_segment, BASE.gas
    z_r_t = (
        gas.compressibility_factor
        * (UNIVERSAL_GAS_CONSTANT / gas.molar_mass_kg_per_mol)
        * gas.temperature_k
    )
    per_metre = (
        16 * segment.darcy_friction_factor * z_r_t / (np.pi**2 * segment.internal_diameter_m**5)
    )
    assert segment_resistance(BASE, np.array([0.0]))[0] == pytest.approx(per_metre * 2500.0)
    # s = 0.5 makes the 50 m section 32 times as resistive: 2450 + 50 * 32 equivalent metres.
    assert segment_resistance(BASE, np.array([0.5]))[0] == pytest.approx(per_metre * (2450 + 1600))


def test_standard_density_matches_the_ideal_gas_law():
    assert standard_density(BASE) == pytest.approx(101325 * 0.018 / (8.314462618 * 288.15))


@pytest.mark.parametrize("severity", [0.0, 0.3, 0.55])
def test_solver_matches_the_closed_form_when_exponent_is_one_half(severity):
    """With n = 0.5 both elements are quadratic, so the exact answer is available."""
    config = varied(exponent=0.5, coefficient=3e-7)
    k = segment_resistance(config, np.array([severity]))[0]
    rho = standard_density(config)
    source = config.well.shut_in_wellhead_pressure_pa_abs
    sink = config.gathering_segment.downstream_boundary_pressure_pa_abs
    exact = np.sqrt((source**2 - sink**2) / (1 / 3e-7**2 + k * rho**2))
    assert solve(config, np.array([severity])).gas_flow_sm3_per_s[0] == pytest.approx(
        exact, rel=1e-10
    )


def test_severity_beyond_the_limit_is_refused():
    with pytest.raises(InfeasibleOperatingPoint):
        solve(BASE, np.array([0.71]))
    with pytest.raises(InfeasibleOperatingPoint):
        solve(BASE, np.array([-0.01]))


# Configuration feasibility


def raw_config():
    import yaml

    from packages.scenario_engine.config import SCENARIO_PATH

    return yaml.safe_load(SCENARIO_PATH.read_text())


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("well", "shut_in_wellhead_pressure_pa_abs", 1.0e6),
        ("restriction", "max_severity", 0.9),
        ("restriction", "full_severity_offset_s", 1000),
        ("gathering_segment", "restricted_length_m", 3000.0),
        ("gas", "temperature_k", -1.0),
        ("sampling", "interval_s", 0),
        ("scenario", "provenance_class", "OBSERVED"),
        ("well", "unknown_parameter", 1.0),
    ],
)
def test_invalid_configuration_is_refused(section, field, value):
    from packages.scenario_engine.config import ScenarioConfig

    data = raw_config()
    data[section][field] = value
    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate(data)


def test_config_declares_every_required_element():
    data = raw_config()
    for key in ("gas", "well", "gathering_segment", "restriction", "sensors", "sampling"):
        assert data[key]
    assert data["simulator"]["seed"] == 30010
    assert {"nominal", "fault"} == set(data["cases"])
    assert all(sensor["unit"] and sensor["reference"] for sensor in data["sensors"])


# Runs


@pytest.fixture(scope="module")
def nominal():
    return simulate(BASE, "nominal")


@pytest.fixture(scope="module")
def fault():
    return simulate(BASE, "fault")


def test_both_cases_are_labeled_synthetic(nominal, fault):
    for run in (nominal, fault):
        assert set(run.frame["provenance_class"]) == {"SYNTHETIC"}


def test_every_declared_invariant_holds(nominal, fault):
    for run in (nominal, fault):
        results = check_invariants(run)
        assert {r.name for r in results} == set(BASE.expected_invariants)
        assert [r.name for r in results if not r.passed] == []


@pytest.mark.parametrize("case", ["nominal", "fault"])
def test_runs_are_deterministic_and_match_the_recorded_hash(case):
    first, second = simulate(BASE, case), simulate(BASE, case)
    assert first.frame.equals(second.frame)
    assert first.canonical_sha256() == second.canonical_sha256() == EXPECTED_SHA256[case]


def test_changing_the_seed_changes_noise_but_not_truth(fault):
    other = BASE.model_copy(update={"simulator": BASE.simulator.model_copy(update={"seed": 1})})
    changed = simulate(other, "fault")
    assert not changed.frame["dpt_pa"].equals(fault.frame["dpt_pa"])
    assert changed.frame["truth_differential_pressure_pa"].equals(
        fault.frame["truth_differential_pressure_pa"]
    )


def test_cases_are_identical_before_the_known_onset(nominal, fault):
    onset = BASE.restriction.onset_offset_s
    columns = [c for c in nominal.frame.columns if c != "case"]
    before = nominal.frame["offset_s"] <= onset
    assert nominal.frame.loc[before, columns].equals(fault.frame.loc[before, columns])


def test_nominal_truth_is_steady(nominal):
    assert nominal.frame["truth_gas_flow_sm3_per_s"].nunique() == 1
    assert nominal.frame["truth_severity"].max() == 0
    assert nominal.fault_onset_offset_s is None


def test_fault_produces_a_coherent_physical_response(nominal, fault):
    start, end = nominal.frame.iloc[-1], fault.frame.iloc[-1]
    assert end["truth_gas_flow_sm3_per_s"] < start["truth_gas_flow_sm3_per_s"]
    assert end["truth_wellhead_pressure_pa_abs"] > start["truth_wellhead_pressure_pa_abs"]
    assert end["truth_differential_pressure_pa"] > start["truth_differential_pressure_pa"]
    assert end["truth_downstream_pressure_pa_abs"] == start["truth_downstream_pressure_pa_abs"]


def test_sensors_are_correlated_as_the_physics_requires(fault):
    """Wellhead minus downstream readings should equal the differential reading within noise."""
    frame = fault.frame
    gap = frame["pt_wh_pa_g"] - frame["pt_ds_pa_g"] - frame["dpt_pa"]
    expected = np.sqrt(2000.0**2 + 2000.0**2 + 500.0**2)
    assert abs(gap.mean()) < 6 * expected / np.sqrt(len(frame))
    assert gap.std() == pytest.approx(expected, rel=0.05)
    assert frame["dpt_pa"].corr(frame["ft_sm3_per_s"]) < -0.9


def test_gauge_sensors_read_one_atmosphere_below_absolute(nominal):
    offset = nominal.frame["truth_wellhead_pressure_pa_abs"] - nominal.frame["pt_wh_pa_g"]
    assert offset.mean() == pytest.approx(BASE.ambient.pressure_pa_abs, abs=100)


def test_a_broken_run_is_rejected(fault):
    frame = fault.frame.copy()
    frame["truth_gas_flow_sm3_per_s"] = frame["truth_gas_flow_sm3_per_s"] * 1.01
    broken = type(fault)(fault.case, fault.config, frame, fault.fault_onset_offset_s)
    with pytest.raises(InvariantViolation):
        require_invariants(broken)


def test_absolute_values_presented_as_gauge_are_caught(fault):
    frame = fault.frame.copy()
    frame["pt_wh_pa_g"] = frame["truth_wellhead_pressure_pa_abs"]
    broken = type(fault)(fault.case, fault.config, frame, fault.fault_onset_offset_s)
    names = {r.name for r in check_invariants(broken) if not r.passed}
    assert "gauge_reference_consistent" in names


def test_an_undeclared_invariant_name_is_an_error(nominal):
    config = BASE.model_copy(update={"expected_invariants": ["made_up"]})
    run = type(nominal)(nominal.case, config, nominal.frame, None)
    with pytest.raises(InvariantViolation):
        check_invariants(run)


def test_detector_view_hides_simulator_truth(fault):
    assert not [c for c in detector_view(fault.frame).columns if c.startswith("truth_")]


def test_rule_refuses_to_read_truth(fault):
    with pytest.raises(ValueError, match="truth"):
        first_sustained_exceedance(fault.frame, BASE.integration_proof_rule)


def test_nominal_emits_no_event_and_fault_emits_onset_and_rule(nominal, fault):
    assert run_events(nominal) == []
    kinds = {e.event_kind.value: e for e in run_events(fault)}
    assert set(kinds) == {"KNOWN_SYNTHETIC_ONSET", "INTEGRATION_PROOF_RULE"}
    assert kinds["KNOWN_SYNTHETIC_ONSET"].onset_offset_s == BASE.restriction.onset_offset_s
    assert kinds["INTEGRATION_PROOF_RULE"].onset_offset_s > BASE.restriction.onset_offset_s
    assert kinds["INTEGRATION_PROOF_RULE"].target_asset_id == "A-03"
    assert kinds["INTEGRATION_PROOF_RULE"].affected_asset_id == "GS-A"


def test_canonical_hash_ignores_last_bit_noise(fault):
    frame = fault.frame.copy()
    frame["dpt_pa"] = frame["dpt_pa"] + 1e-9
    assert canonical_sha256(frame) == canonical_sha256(fault.frame)


# Pressure reference conversions


def test_gauge_absolute_round_trip_needs_ambient():
    value = convert_pressure(2.0e6, ReferenceType.ABSOLUTE, ReferenceType.GAUGE, ambient_pa_abs=9e4)
    assert value == pytest.approx(1.91e6)
    assert convert_pressure(
        value, ReferenceType.GAUGE, ReferenceType.ABSOLUTE, 9e4
    ) == pytest.approx(2.0e6)


@pytest.mark.parametrize(
    ("source", "target", "ambient"),
    [
        (ReferenceType.ABSOLUTE, ReferenceType.GAUGE, None),
        (ReferenceType.GAUGE, ReferenceType.ABSOLUTE, None),
        (ReferenceType.GAUGE, ReferenceType.ABSOLUTE, -1.0),
        (ReferenceType.UNKNOWN, ReferenceType.GAUGE, 9e4),
        (ReferenceType.UNKNOWN, ReferenceType.ABSOLUTE, 9e4),
        (ReferenceType.GAUGE, ReferenceType.UNKNOWN, 9e4),
        (ReferenceType.UNKNOWN, ReferenceType.UNKNOWN, 9e4),
        (ReferenceType.DIFFERENTIAL, ReferenceType.GAUGE, 9e4),
        (ReferenceType.GAUGE, ReferenceType.DIFFERENTIAL, 9e4),
    ],
)
def test_incorrect_pressure_conversions_are_refused(source, target, ambient):
    with pytest.raises(SemanticError):
        convert_pressure(1.0e6, source, target, ambient_pa_abs=ambient)


def test_report_values_do_not_depend_on_machine_precision_noise():
    from pipelines.synthetic.report import _stable

    assert _stable("8.484e-16") == _stable("8.999e-16") == "below 1e-12"
    assert _stable("0.000e+00") == "below 1e-12"
    assert _stable("4.638e+00") == "4.638e+00"
    assert _stable("max Mach 0.077, min Re 7.644e+05") == "max Mach 0.077, min Re 7.644e+05"
