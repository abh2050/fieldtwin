"""Varied AETHER runs for the Gate 5 benchmark, built on the accepted Gate 4 solver and sensors.

Gate 4's modules and hashes are untouched. A case supplies its own parameters, and the solver,
telemetry layer, and fault definitions are reused. Fault truth stays in `labels`, apart from the
telemetry that detectors read. Everything here is SYNTHETIC, from an uncalibrated fictional model.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from typing import cast

import numpy as np
import pandas as pd
import yaml

from .field_scenarios import (
    Category,
    CommunicationFault,
    FieldScenario,
    PhysicalFault,
    PlannedOperation,
    SensorFault,
)
from .field_simulation import GOOD, _telemetry, _truth_frame, build_sensors, default_setup
from .network_graph import REPO_ROOT, NetworkConfig
from .network_solver import NetworkModel, NetworkState

DESIGN_PATH = REPO_ROOT / "config" / "experiments" / "aether_benchmark.yaml"
SENSOR_CATEGORIES = ("SENSOR_BIAS", "SENSOR_DRIFT", "SENSOR_STUCK")
BALANCE_LIMIT = 1.0e-8


class CaseRefused(ValueError):
    """A case left the simulator's declared validity envelope, so it gives no result."""


@lru_cache(maxsize=1)
def load_design() -> dict:
    return yaml.safe_load(DESIGN_PATH.read_text())


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    split: str
    regime: str
    category: str
    seed: int
    well_multipliers: tuple[tuple[str, float], ...]
    noise_multiplier: float
    unit_capacity: tuple[tuple[str, float], ...]
    units_offline: tuple[str, ...]
    # (start offset, setpoint) steps. Normal operating variation, known to no detector.
    setpoint_steps: tuple[tuple[int, float], ...]
    physical_faults: tuple[PhysicalFault, ...] = ()
    sensor_faults: tuple[SensorFault, ...] = ()
    stuck_tag: str | None = None
    stuck_onset_s: int | None = None
    communication_faults: tuple[CommunicationFault, ...] = ()
    planned_operations: tuple[PlannedOperation, ...] = field(default=())

    # The attributes below let Gate 4's truth and telemetry functions read a case like a scenario.
    @property
    def scenario_id(self) -> str:
        return self.case_id

    @property
    def run_id(self) -> str:
        return f"{self.case_id}:seed{self.seed}"

    @property
    def first_onset_s(self) -> int | None:
        return fault_onset_s(self)

    def state_at(self, offset_s: int) -> NetworkState:
        severity = tuple(
            (f.asset_id, f.value_at(offset_s))
            for f in self.physical_faults
            if f.kind == "SEGMENT_RESTRICTION" and f.value_at(offset_s) > 0
        )
        fractions = {unit: 0.0 for unit in self.units_offline}
        for fault in self.physical_faults:
            if fault.kind == "COMPRESSOR_DERATE" and fault.value_at(offset_s) < 1:
                fractions[fault.asset_id] = fault.value_at(offset_s)
        closed, shut_in = set(), set()
        for operation in self.planned_operations:
            if operation.active(offset_s):
                if operation.kind == "CLOSE_VALVE":
                    closed.add(operation.asset_id)
                elif operation.kind == "SHUT_IN_WELL":
                    shut_in.add(operation.asset_id)
                else:
                    fractions[operation.asset_id] = 0.0
        return NetworkState(
            severity, frozenset(closed), frozenset(shut_in), tuple(sorted(fractions.items()))
        )

    def parameters(self) -> dict:
        return json.loads(json.dumps(dataclasses.asdict(self), default=str))

    def parameter_sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.parameters(), sort_keys=True).encode()).hexdigest()


def fault_onset_s(case: BenchmarkCase) -> int | None:
    """When the anomaly being scored begins. Planned work and dropouts aren't anomalies here."""
    onsets = [f.onset_s for f in case.physical_faults] + [f.onset_s for f in case.sensor_faults]
    if case.stuck_onset_s is not None:
        onsets.append(case.stuck_onset_s)
    return min(onsets) if onsets else None


def class_name(case: BenchmarkCase) -> str:
    if case.category in SENSOR_CATEGORIES:
        return "SENSOR"
    if case.category in ("RESTRICTION", "DERATE"):
        return case.category
    return "NORMAL"


def _uniform(rng: np.random.Generator, bounds: list[float]) -> float:
    return float(rng.uniform(bounds[0], bounds[1]))


def _band(rng: np.random.Generator, bands: list[list[float]]) -> float:
    return _uniform(rng, bands[int(rng.integers(len(bands)))])


def build_case(
    case_id: str, split: str, regime: str, category: str, seed: int, ranges: dict
) -> BenchmarkCase:
    config = default_setup()[0]
    rng = np.random.default_rng(np.random.SeedSequence([seed, zlib.crc32(category.encode())]))
    duration = load_design()["duration_s"]
    interval = load_design()["interval_s"]

    def well_multiplier() -> float:
        if "well_multiplier_bands" in ranges:
            return _band(rng, ranges["well_multiplier_bands"])
        return _uniform(rng, ranges["well_multiplier"])

    wells = tuple((w.id, round(well_multiplier(), 6)) for w in config.wells)
    noise = round(_uniform(rng, ranges["noise_multiplier"]), 6)
    units = [u.id for u in config.compression.units]
    capacity = tuple((u, round(_uniform(rng, ranges["unit_capacity_sm3_per_s"]), 6)) for u in units)
    offline = tuple(units[-ranges["units_offline"] :]) if ranges["units_offline"] else ()

    if "setpoint_bands" in ranges:
        base = _band(rng, ranges["setpoint_bands"])
    else:
        base = _uniform(rng, ranges["setpoint_pa_abs"])
    steps, now = [], 0
    while now < duration:
        step = rng.uniform(-1.0, 1.0) * ranges["setpoint_step_fraction"]
        steps.append((now, round(base * (1.0 + step), 1)))
        now += int(_uniform(rng, ranges["setpoint_hold_hours"]) * 3600) // interval * interval

    def onset() -> int:
        if "onset_day_bands" in ranges:
            days = _band(rng, ranges["onset_day_bands"])
        else:
            days = _uniform(rng, ranges["onset_days"])
        return int(days * 86400) // interval * interval

    planned: list[PlannedOperation] = []
    minimum, maximum = ranges["planned_per_case"]
    count = int(rng.integers(max(minimum, 1), maximum + 1)) if category == "PLANNED" else 0
    for _ in range(count):
        start = int(_uniform(rng, [1.0, 6.0]) * 86400) // interval * interval
        length = int(_uniform(rng, ranges["planned_hours"]) * 3600) // interval * interval
        well = str(rng.choice([w.id for w in config.wells]))
        planned.append(
            PlannedOperation(
                kind="SHUT_IN_WELL", asset_id=well, start_s=start, end_s=start + length
            )
        )

    physical: list[PhysicalFault] = []
    sensor: list[SensorFault] = []
    stuck_tag, stuck_onset = None, None
    comms: list[CommunicationFault] = []
    if category == "RESTRICTION":
        start = onset()
        physical.append(
            PhysicalFault(
                kind="SEGMENT_RESTRICTION",
                asset_id=str(rng.choice(ranges["restriction_assets"])),
                onset_s=start,
                full_s=start
                + int(_uniform(rng, ranges["ramp_days"]) * 86400) // interval * interval,
                max_severity=round(_uniform(rng, ranges["severity"]), 6),
            )
        )
    elif category == "DERATE":
        start = onset()
        physical.append(
            PhysicalFault(
                kind="COMPRESSOR_DERATE",
                asset_id=str(rng.choice(ranges["derate_assets"])),
                onset_s=start,
                full_s=start
                + int(_uniform(rng, ranges["ramp_days"]) * 86400) // interval * interval,
                final_fraction=round(_uniform(rng, ranges["derate_final_fraction"]), 6),
            )
        )
    elif category in SENSOR_CATEGORIES:
        start = onset()
        use_pressure = bool(rng.integers(2))
        tag = str(
            rng.choice(ranges["sensor_tags_pressure" if use_pressure else "sensor_tags_flow"])
        )
        if category == "SENSOR_BIAS":
            size = _uniform(rng, ranges["bias_pa" if use_pressure else "bias_flow"])
            sensor.append(
                SensorFault(kind="BIAS", tag=tag, onset_s=start, magnitude=round(size, 6))
            )
        elif category == "SENSOR_DRIFT":
            rate = _uniform(
                rng, ranges["drift_pa_per_day" if use_pressure else "drift_flow_per_day"]
            )
            sensor.append(
                SensorFault(kind="DRIFT", tag=tag, onset_s=start, rate_per_day=round(rate, 6))
            )
        else:
            stuck_tag, stuck_onset = tag, start
    if category == "COMM" or (
        ranges.get("overlay_dropout") and category not in ("NORMAL", "PLANNED")
    ):
        start = int(_uniform(rng, [1.0, 6.0]) * 86400) // interval * interval
        length = int(_uniform(rng, ranges["dropout_hours"]) * 3600) // interval * interval
        comms.append(
            CommunicationFault(
                group=str(rng.choice(ranges["dropout_groups"])), onset_s=start, end_s=start + length
            )
        )
    return BenchmarkCase(
        case_id=case_id,
        split=split,
        regime=regime,
        category=category,
        seed=seed,
        well_multipliers=wells,
        noise_multiplier=noise,
        unit_capacity=capacity,
        units_offline=offline,
        setpoint_steps=tuple(steps),
        physical_faults=tuple(physical),
        sensor_faults=tuple(sensor),
        stuck_tag=stuck_tag,
        stuck_onset_s=stuck_onset,
        communication_faults=tuple(comms),
        planned_operations=tuple(planned),
    )


def all_cases() -> list[BenchmarkCase]:
    """The full design, fixed by the configuration alone."""
    design = load_design()
    cases = []
    for split, per_category in design["cases_per_category"].items():
        seed = design["seed_base"][split]
        for category in design["categories"]:
            for i in range(per_category):
                seed += 1
                cases.append(
                    build_case(
                        f"{split}-{category}-{i:02d}",
                        split,
                        "in_regime",
                        category,
                        seed,
                        design["regime"],
                    )
                )
    seed = design["seed_base"]["held_out"]
    for regime, changes in design["held_out_regimes"].items():
        ranges = {**design["regime"], **changes}
        for category in design["held_out_categories"]:
            for i in range(design["held_out_cases_per_category"]):
                seed += 1
                cases.append(
                    build_case(
                        f"held-{regime}-{category}-{i:02d}",
                        "held_out",
                        regime,
                        category,
                        seed,
                        ranges,
                    )
                )
    return cases


def _config_for(case: BenchmarkCase, setpoint: float) -> NetworkConfig:
    base = default_setup()[0]
    multiplier = dict(case.well_multipliers)
    capacity = dict(case.unit_capacity)
    wells = [
        w.model_copy(update={"coefficient": w.coefficient * multiplier[w.id]}) for w in base.wells
    ]
    units = [
        u.model_copy(update={"capacity_sm3_per_s": capacity[u.id]}) for u in base.compression.units
    ]
    compression = base.compression.model_copy(
        update={"suction_setpoint_pa_abs": setpoint, "units": units}
    )
    return base.model_copy(update={"wells": wells, "compression": compression})


def _check_envelope(case: BenchmarkCase, truth: pd.DataFrame, config: NetworkConfig) -> None:
    """The same limits Gate 4 applies, read against this case's parameters."""
    limits = config.validity_envelope
    if truth["truth_max_mach"].max() > limits.max_mach_number:
        raise CaseRefused(f"{case.case_id}: Mach {truth['truth_max_mach'].max():.3f}")
    flowing = truth["truth_total_flow"] > 0
    if (
        flowing.any()
        and truth.loc[flowing, "truth_min_reynolds"].min() < limits.min_reynolds_number_when_flowing
    ):
        raise CaseRefused(f"{case.case_id}: Reynolds below the limit")
    pressures = truth[[c for c in truth.columns if c.startswith("truth_p_")]].to_numpy()
    if (
        np.nanmax(pressures) > limits.max_pressure_pa_abs
        or np.nanmin(pressures) < limits.min_pressure_pa_abs
    ):
        raise CaseRefused(f"{case.case_id}: pressure outside the envelope")
    severity = truth[[c for c in truth.columns if c.startswith("truth_severity_")]].to_numpy()
    if severity.max() > limits.severity_limit:
        raise CaseRefused(f"{case.case_id}: severity above the limit")
    suction = truth["truth_p_COMP-SUCTION"].to_numpy()
    if (
        config.compression.discharge_pa_abs / suction
    ).max() > config.compression.max_compression_ratio:
        raise CaseRefused(f"{case.case_id}: compression ratio above the limit")
    graph = default_setup()[1]
    for node in graph.nodes.values():
        if node.node_type.value in ("SITE", "RESERVOIR_BOUNDARY", "DISCHARGE_BOUNDARY"):
            continue
        balance = np.zeros(len(truth))
        for edge in graph.flow_edges():
            if edge.target == node.node_id:
                balance += truth[f"truth_q_{edge.edge_id}"].to_numpy()
            if edge.source == node.node_id:
                balance -= truth[f"truth_q_{edge.edge_id}"].to_numpy()
        if np.abs(balance).max() > BALANCE_LIMIT:
            raise CaseRefused(f"{case.case_id}: mass balance failed at {node.node_id}")


@dataclass(frozen=True)
class BenchmarkRun:
    case: BenchmarkCase
    telemetry: pd.DataFrame  # Wide: offset_s plus one column per tag. Bad quality is NaN.
    labels: pd.DataFrame  # Fault truth. Detectors never read this.


def simulate_case(case: BenchmarkCase) -> BenchmarkRun:
    design = load_design()
    _, graph, _, catalog, default_sensors = default_setup()
    offsets = np.arange(0, design["duration_s"], design["interval_s"], dtype=np.int64)
    starts = [s for s, _ in case.setpoint_steps]
    level = np.searchsorted(starts, offsets, side="right") - 1
    frames, config = [], None
    for index, (_, setpoint) in enumerate(case.setpoint_steps):
        chosen = offsets[level == index]
        if chosen.size == 0:
            continue
        config = _config_for(case, setpoint)
        truth, _ = _truth_frame(NetworkModel(config, graph), cast(FieldScenario, case), chosen)
        _check_envelope(case, truth, config)
        frames.append(truth)
    if config is None:
        raise CaseRefused(f"{case.case_id}: no samples")
    truth = pd.concat(frames, ignore_index=True)
    sensors = [
        dataclasses.replace(s, noise_std=s.noise_std * case.noise_multiplier)
        for s in default_sensors
    ]
    simulation = catalog.simulation.model_copy(update={"seed": case.seed})
    long = _telemetry(
        cast(FieldScenario, case),
        truth,
        NetworkModel(config, graph),
        sensors,
        catalog.model_copy(update={"simulation": simulation}),
        case.parameter_sha256(),
        case.run_id,
    )
    good = long["quality"] == GOOD
    wide = long.assign(value=long["value"].where(good)).pivot(
        index="offset_s", columns="tag", values="value"
    )
    wide = wide[[s.tag for s in sensors]].reset_index()
    wide.columns.name = None
    if case.stuck_tag is not None:
        stuck = wide["offset_s"] >= case.stuck_onset_s
        wide.loc[stuck, case.stuck_tag] = wide.loc[~stuck, case.stuck_tag].iloc[-1]
    return BenchmarkRun(case, wide, _labels(case, offsets))


def _labels(case: BenchmarkCase, offsets: np.ndarray) -> pd.DataFrame:
    classes = load_design()["classes"]
    onset = fault_onset_s(case)
    y = np.zeros(len(offsets), dtype=np.int8)
    if onset is not None:
        y[offsets >= onset] = classes[class_name(case)]
    planned = np.zeros(len(offsets), dtype=bool)
    for operation in case.planned_operations:
        planned |= (offsets >= operation.start_s) & (offsets < operation.end_s)
    dropout = np.zeros(len(offsets), dtype=bool)
    for fault in case.communication_faults:
        dropout |= (offsets >= fault.onset_s) & (offsets < fault.end_s)
    return pd.DataFrame(
        {"offset_s": offsets, "y": y, "planned_active": planned, "dropout_active": dropout}
    )


def sensor_tags() -> list[str]:
    config, graph, _, _, _ = default_setup()
    return [s.tag for s in build_sensors(config, graph)]


__all__ = ["BenchmarkCase", "BenchmarkRun", "CaseRefused", "Category", "all_cases", "simulate_case"]
