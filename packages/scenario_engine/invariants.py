"""Declared physical invariants, evaluated on a finished run. A failure rejects the run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .config import ScenarioConfig
from .physics import segment_resistance, standard_density
from .simulate import SimulationRun

RELATIVE_TOLERANCE = 1e-9
NOISE_SIGMA_BOUND = 6.0


class InvariantViolation(ValueError):
    """A run broke a declared physical invariant."""


@dataclass(frozen=True)
class InvariantResult:
    name: str
    passed: bool
    measured: str


def _result(name: str, passed: object, measured: float | str) -> InvariantResult:
    text = f"{measured:.3e}" if isinstance(measured, float) else str(measured)
    return InvariantResult(name, bool(passed), text)


def _arrays(run: SimulationRun) -> dict[str, np.ndarray]:
    frame = run.frame
    return {
        "q": frame["truth_gas_flow_sm3_per_s"].to_numpy(),
        "wellhead": frame["truth_wellhead_pressure_pa_abs"].to_numpy(),
        "downstream": frame["truth_downstream_pressure_pa_abs"].to_numpy(),
        "dp": frame["truth_differential_pressure_pa"].to_numpy(),
        "severity": frame["truth_severity"].to_numpy(),
    }


def _inflow_flow(config: ScenarioConfig, wellhead: np.ndarray) -> np.ndarray:
    well = config.well
    return (
        well.deliverability_coefficient
        * (well.shut_in_wellhead_pressure_pa_abs**2 - wellhead**2) ** well.deliverability_exponent
    )


def mass_conservation(run: SimulationRun) -> InvariantResult:
    """The flow the well delivers at the solved pressure must equal the flow in the segment."""
    a = _arrays(run)
    residual = np.abs(_inflow_flow(run.config, a["wellhead"]) - a["q"]) / a["q"]
    return _result("mass_conservation", residual.max() < 1e-6, float(residual.max()))


def pressure_ordering(run: SimulationRun) -> InvariantResult:
    a = _arrays(run)
    source = run.config.well.shut_in_wellhead_pressure_pa_abs
    ordered = (source > a["wellhead"]).all() and (a["wellhead"] > a["downstream"]).all()
    return _result("pressure_ordering", ordered, "p_shut_in > p_wellhead > p_downstream")


def inflow_equation_residual(run: SimulationRun) -> InvariantResult:
    a = _arrays(run)
    well = run.config.well
    left = well.shut_in_wellhead_pressure_pa_abs**2 - a["wellhead"] ** 2
    right = (a["q"] / well.deliverability_coefficient) ** (1.0 / well.deliverability_exponent)
    residual = np.abs(left - right) / left
    return _result("inflow_equation_residual", residual.max() < 1e-6, float(residual.max()))


def segment_equation_residual(run: SimulationRun) -> InvariantResult:
    a = _arrays(run)
    config = run.config
    left = a["wellhead"] ** 2 - a["downstream"] ** 2
    mass = standard_density(config) * a["q"]
    right = segment_resistance(config, a["severity"]) * mass**2
    residual = np.abs(left - right) / left
    return _result("segment_equation_residual", residual.max() < 1e-6, float(residual.max()))


def differential_definition(run: SimulationRun) -> InvariantResult:
    a = _arrays(run)
    residual = np.abs(a["wellhead"] - a["downstream"] - a["dp"])
    return _result("differential_definition", residual.max() < 1e-3, float(residual.max()))


def positive_flow(run: SimulationRun) -> InvariantResult:
    minimum = float(_arrays(run)["q"].min())
    return _result("positive_flow", minimum > 0, minimum)


def flow_regime_valid(run: SimulationRun) -> InvariantResult:
    limits = run.config.operating_limits
    mach = float(run.frame["truth_mach_number"].max())
    reynolds = float(run.frame["truth_reynolds_number"].min())
    passed = mach <= limits.max_mach_number and reynolds >= limits.min_reynolds_number
    return _result("flow_regime_valid", passed, f"max Mach {mach:.3f}, min Re {reynolds:.3e}")


def severity_bounds_and_monotonic(run: SimulationRun) -> InvariantResult:
    severity = _arrays(run)["severity"]
    limit = run.config.restriction.severity_limit
    passed = bool((severity >= 0).all() and (severity <= limit).all())
    passed = passed and bool((np.diff(severity) >= 0).all())
    offsets = run.frame["offset_s"].to_numpy()
    if run.fault_onset_offset_s is None:
        passed = passed and bool((severity == 0).all())
    else:
        passed = passed and bool((severity[offsets <= run.fault_onset_offset_s] == 0).all())
    return _result("severity_bounds_and_monotonic", passed, f"max {severity.max():.3f}")


def severity_response_monotonic(run: SimulationRun) -> InvariantResult:
    """More restriction means less flow, higher wellhead pressure, and a larger differential."""
    a = _arrays(run)
    growing = np.diff(a["severity"]) > 0
    tolerance = RELATIVE_TOLERANCE
    passed = bool(
        (np.diff(a["q"])[growing] <= tolerance).all()
        and (np.diff(a["wellhead"])[growing] >= -tolerance * a["wellhead"][0]).all()
        and (np.diff(a["dp"])[growing] >= -tolerance * a["wellhead"][0]).all()
    )
    return _result("severity_response_monotonic", passed, f"{int(growing.sum())} steps checked")


def noise_within_bounds(run: SimulationRun) -> InvariantResult:
    """Sensor error stays near its declared size, and each sensor reports what it says it does."""
    config, frame = run.config, run.frame
    ambient = config.ambient.pressure_pa_abs
    worst = 0.0
    for sensor in config.sensors:
        truth = frame[sensor.truth_column].to_numpy()
        reference = truth - ambient if sensor.reference == "GAUGE" else truth
        error = frame[sensor.column].to_numpy() - reference
        worst = max(worst, float(np.abs(error).max() / sensor.noise_std))
    return _result("noise_within_bounds", worst <= NOISE_SIGMA_BOUND, worst)


def gauge_reference_consistent(run: SimulationRun) -> InvariantResult:
    """Gauge sensors must sit about one atmosphere below absolute truth, not on it."""
    config, frame = run.config, run.frame
    ambient = config.ambient.pressure_pa_abs
    worst = 0.0
    for sensor in config.sensors:
        if sensor.reference != "GAUGE":
            continue
        offset = (frame[sensor.truth_column] - frame[sensor.column]).mean()
        worst = max(worst, abs(float(offset) - ambient))
    # The mean of the noise over n samples shrinks with sqrt(n).
    limit = 6.0 * max(s.noise_std for s in config.sensors) / np.sqrt(len(frame))
    return _result("gauge_reference_consistent", worst <= limit, worst)


def nominal_envelope(run: SimulationRun) -> InvariantResult:
    """The zero-severity state must lie inside the declared nominal operating range."""
    a = _arrays(run)
    limits = run.config.operating_limits
    clean = a["severity"] == 0
    flow, wellhead = a["q"][clean], a["wellhead"][clean]
    passed = bool(
        (flow >= limits.nominal_flow_sm3_per_s.min).all()
        and (flow <= limits.nominal_flow_sm3_per_s.max).all()
        and (wellhead >= limits.nominal_wellhead_pressure_pa_abs.min).all()
        and (wellhead <= limits.nominal_wellhead_pressure_pa_abs.max).all()
    )
    return _result("nominal_envelope", passed, f"q {flow.mean():.3f} sm3/s")


_CHECKS: dict[str, Callable[[SimulationRun], InvariantResult]] = {
    check.__name__: check
    for check in (
        mass_conservation,
        pressure_ordering,
        inflow_equation_residual,
        segment_equation_residual,
        differential_definition,
        positive_flow,
        flow_regime_valid,
        severity_bounds_and_monotonic,
        severity_response_monotonic,
        noise_within_bounds,
        gauge_reference_consistent,
        nominal_envelope,
    )
}


def check_invariants(run: SimulationRun) -> list[InvariantResult]:
    """Run every invariant the configuration declares. An undeclared name is an error."""
    unknown = set(run.config.expected_invariants) - set(_CHECKS)
    if unknown:
        raise InvariantViolation(f"configuration names unknown invariants: {sorted(unknown)}")
    return [_CHECKS[name](run) for name in run.config.expected_invariants]


def require_invariants(run: SimulationRun) -> list[InvariantResult]:
    results = check_invariants(run)
    failed = [r for r in results if not r.passed]
    if failed:
        raise InvariantViolation("; ".join(f"{r.name} ({r.measured})" for r in failed))
    return results
