"""Generate deterministic synthetic telemetry for one case. Modular so Gate 4 can add wells."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from packages.domain.models import ReferenceType
from packages.domain.semantics import convert_pressure

from .config import ScenarioConfig, Sensor
from .physics import restriction_schedule, solve

PROVENANCE = "SYNTHETIC"
PRODUCING = "PRODUCING"
NO_FAULT, RESTRICTION_GROWING, RESTRICTION_HELD = (
    "NO_FAULT",
    "RESTRICTION_GROWING",
    "RESTRICTION_HELD",
)
_ROUNDING = {"truth_severity": 9, "ft_sm3_per_s": 6, "truth_gas_flow_sm3_per_s": 6}
_DEFAULT_DECIMALS = 3


@dataclass(frozen=True)
class SimulationRun:
    case: str
    config: ScenarioConfig
    frame: pd.DataFrame
    fault_onset_offset_s: int | None

    @property
    def run_id(self) -> str:
        scenario = self.config.scenario
        return f"{scenario.scenario_id}:v{scenario.version}:{self.case}"

    def canonical_sha256(self) -> str:
        """Hash of rounded values, so a last-bit difference between platforms can't change it."""
        return canonical_sha256(self.frame)


def canonical_sha256(frame: pd.DataFrame) -> str:
    rounded = frame.copy()
    for column in rounded.select_dtypes("number").columns:
        rounded[column] = rounded[column].round(_ROUNDING.get(column, _DEFAULT_DECIMALS))
    return hashlib.sha256(rounded.to_csv(index=False, float_format="%.9f").encode()).hexdigest()


def _sensor_values(sensor: Sensor, frame: pd.DataFrame, ambient: float) -> np.ndarray:
    truth = frame[sensor.truth_column].to_numpy()
    if sensor.reference == "GAUGE":
        return convert_pressure(
            truth, ReferenceType.ABSOLUTE, ReferenceType.GAUGE, ambient_pa_abs=ambient
        )
    return truth


def apply_sensors(config: ScenarioConfig, frame: pd.DataFrame) -> pd.DataFrame:
    """Add noisy readings. Each sensor has its own stream, so one can't disturb the others."""
    streams = np.random.SeedSequence(config.simulator.seed).spawn(len(config.sensors))
    for sensor, stream in zip(config.sensors, streams, strict=True):
        generator = np.random.Generator(np.random.PCG64(stream))
        noise = generator.normal(0.0, sensor.noise_std, len(frame))
        values = _sensor_values(sensor, frame, config.ambient.pressure_pa_abs) + noise
        # A flow meter can't read below zero. Pressure transmitters can read small negatives.
        if sensor.quantity == "standard_volume_flow":
            values = np.maximum(values, 0.0)
        frame[sensor.column] = values
    return frame


def simulate(config: ScenarioConfig, case: str) -> SimulationRun:
    if case not in config.cases:
        raise ValueError(f"unknown case {case!r}")
    enabled = config.cases[case].restriction_enabled
    offsets = np.arange(0, config.sampling.duration_s, config.sampling.interval_s, dtype=np.int64)
    severity = (
        restriction_schedule(config, offsets.astype(float))
        if enabled
        else np.zeros(len(offsets), dtype=float)
    )
    point = solve(config, severity)

    fault_state = np.full(len(offsets), NO_FAULT, dtype=object)
    if enabled:
        schedule = config.restriction
        fault_state[offsets > schedule.onset_offset_s] = RESTRICTION_GROWING
        fault_state[offsets >= schedule.full_severity_offset_s] = RESTRICTION_HELD

    # Columns starting with truth_ are simulator ground truth. Detectors must read only sensors.
    frame = pd.DataFrame(
        {
            "offset_s": offsets,
            "provenance_class": PROVENANCE,
            "case": case,
            "operational_state": PRODUCING,
            "truth_fault_state": fault_state,
            "truth_severity": severity,
            "truth_gas_flow_sm3_per_s": point.gas_flow_sm3_per_s,
            "truth_wellhead_pressure_pa_abs": point.wellhead_pressure_pa_abs,
            "truth_downstream_pressure_pa_abs": point.downstream_pressure_pa_abs,
            "truth_differential_pressure_pa": point.differential_pressure_pa,
            "truth_mach_number": point.mach_number,
            "truth_reynolds_number": point.reynolds_number,
        }
    )
    frame = apply_sensors(config, frame)
    onset = config.restriction.onset_offset_s if enabled else None
    return SimulationRun(case=case, config=config, frame=frame, fault_onset_offset_s=onset)


def detector_view(frame: pd.DataFrame) -> pd.DataFrame:
    """What a detector may see: time, state, and sensors. Ground truth is removed."""
    return frame[[c for c in frame.columns if not c.startswith("truth_")]]
