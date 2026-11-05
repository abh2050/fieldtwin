"""Steady isothermal gas flow through a well and one gathering segment in series.

Both elements carry the same standard flow q, so mass is conserved by construction:

    inflow:   q = C (p_s^2 - p_wh^2)^n
    segment:  p_wh^2 - p_d^2 = K(s) m^2,  m = rho_std q
    K(s) = 16 f Z R T / (pi^2 D^5) * [ (L - L_r) + L_r / (1 - s)^5 ]

Severity s is the fractional loss of hydraulic diameter over the restricted length L_r. The segment
equation is the isothermal compressible pipe equation without elevation or acceleration terms.
Friction factor and compressibility are held constant. All pressures are absolute pascals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import UNIVERSAL_GAS_CONSTANT, ScenarioConfig

_BISECTION_STEPS = 200


class InfeasibleOperatingPoint(ValueError):
    """The requested state has no physical forward-flow solution within the model's scope."""


@dataclass(frozen=True)
class OperatingPoint:
    gas_flow_sm3_per_s: np.ndarray
    mass_flow_kg_per_s: np.ndarray
    wellhead_pressure_pa_abs: np.ndarray
    downstream_pressure_pa_abs: np.ndarray
    differential_pressure_pa: np.ndarray
    resistance: np.ndarray
    mach_number: np.ndarray
    reynolds_number: np.ndarray


def standard_density(config: ScenarioConfig) -> float:
    """Gas density at standard conditions, treating the gas as ideal at that low pressure."""
    std = config.standard_conditions
    return (
        std.pressure_pa_abs
        * config.gas.molar_mass_kg_per_mol
        / (UNIVERSAL_GAS_CONSTANT * std.temperature_k)
    )


def segment_resistance(config: ScenarioConfig, severity: np.ndarray) -> np.ndarray:
    """K(s) in Pa^2 per (kg/s)^2. Rises monotonically and without bound as s approaches 1."""
    severity = np.asarray(severity, dtype=float)
    if np.any(severity < 0) or np.any(severity > config.restriction.severity_limit):
        raise InfeasibleOperatingPoint(
            f"severity must stay within 0 to {config.restriction.severity_limit}"
        )
    segment, gas = config.gathering_segment, config.gas
    base = (
        16.0
        * segment.darcy_friction_factor
        * gas.compressibility_factor
        * gas.specific_gas_constant
        * gas.temperature_k
        / (np.pi**2 * segment.internal_diameter_m**5)
    )
    open_length = segment.length_m - segment.restricted_length_m
    return base * (open_length + segment.restricted_length_m / (1.0 - severity) ** 5)


def solve(config: ScenarioConfig, severity: np.ndarray) -> OperatingPoint:
    """Find the flow where inflow and segment agree. The balance is monotonic in q, so bisect."""
    severity = np.asarray(severity, dtype=float)
    well, segment, gas = config.well, config.gathering_segment, config.gas
    source = well.shut_in_wellhead_pressure_pa_abs
    sink = segment.downstream_boundary_pressure_pa_abs
    if source <= sink:
        raise InfeasibleOperatingPoint("no forward flow: shut-in pressure must exceed downstream")

    resistance = segment_resistance(config, severity)
    density = standard_density(config)
    coefficient, exponent = well.deliverability_coefficient, well.deliverability_exponent
    available = source**2 - sink**2

    def imbalance(q: np.ndarray) -> np.ndarray:
        return available - (q / coefficient) ** (1.0 / exponent) - resistance * (density * q) ** 2

    low = np.zeros_like(severity)
    high = np.full_like(severity, coefficient * available**exponent)
    for _ in range(_BISECTION_STEPS):
        middle = 0.5 * (low + high)
        positive = imbalance(middle) > 0
        low = np.where(positive, middle, low)
        high = np.where(positive, high, middle)
    flow = 0.5 * (low + high)

    mass = density * flow
    wellhead = np.sqrt(sink**2 + resistance * mass**2)

    # Local conditions at the narrowest section, where velocity is highest.
    throat = segment.internal_diameter_m * (1.0 - severity)
    area = np.pi * throat**2 / 4.0
    z_r_t = gas.compressibility_factor * gas.specific_gas_constant * gas.temperature_k
    # Density at the outlet pressure, the lowest in the segment, gives the highest velocity.
    local_density = sink / z_r_t
    velocity = mass / (local_density * area)
    mach = velocity / np.sqrt(gas.heat_capacity_ratio * z_r_t)
    reynolds = local_density * velocity * throat / gas.dynamic_viscosity_pa_s

    return OperatingPoint(
        gas_flow_sm3_per_s=flow,
        mass_flow_kg_per_s=mass,
        wellhead_pressure_pa_abs=wellhead,
        downstream_pressure_pa_abs=np.full_like(flow, sink),
        differential_pressure_pa=wellhead - sink,
        resistance=resistance,
        mach_number=mach,
        reynolds_number=reynolds,
    )


def restriction_schedule(config: ScenarioConfig, offsets_s: np.ndarray) -> np.ndarray:
    """Severity over time: zero, then a linear ramp from onset to full severity, then held."""
    schedule = config.restriction
    ramp = (offsets_s - schedule.onset_offset_s) / (
        schedule.full_severity_offset_s - schedule.onset_offset_s
    )
    return schedule.max_severity * np.clip(ramp, 0.0, 1.0)
