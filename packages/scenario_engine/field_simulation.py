"""Run a field scenario: truth from the coupled solver, then sensors and communications on top.

Truth and telemetry are separate tables. A sensor or communication fault changes what is reported,
and it can't change the physics, because telemetry is computed after the solve.
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from packages.domain.models import ReferenceType
from packages.domain.semantics import convert_pressure

from .field_scenarios import Category, FieldCatalog, FieldScenario, load_catalog
from .network_graph import WELLHEAD_PREFIX, NetworkConfig, NetworkGraph, build_graph, load_network
from .network_solver import (
    COMPRESSOR_STATE_CODE,
    NetworkModel,
    NetworkSolution,
    NetworkState,
    solve_network,
)

PROVENANCE = "SYNTHETIC"
GOOD, BAD_COMM, BAD_NOT_MEASURABLE = "GOOD", "BAD_COMM_LOST", "BAD_NOT_MEASURABLE"
OK, COMM_LOST, NOT_MEASURABLE = "OK", "COMM_LOST", "NOT_MEASURABLE"
PRESSURE_NOISE_PA = 2000.0
DP_NOISE_PA = 500.0
FLOW_NOISE = 0.0015
_DECIMALS = {"Pa": 0, "sm3_per_s": 5, "state_code": 0}


@dataclass(frozen=True)
class FieldSensor:
    tag: str
    asset_id: str
    equipment_class_id: str
    measurement_definition_id: str
    quantity: str
    reference: str
    unit: str
    display_unit: str
    noise_std: float
    source_kind: str  # NODE, DIFFERENTIAL, EDGE_FLOW, or COMPRESSOR_STATE
    source_id: str
    groups: tuple[str, ...]


def build_sensors(config: NetworkConfig, graph: NetworkGraph) -> list[FieldSensor]:
    """The instrument list, derived from the network so it can't name equipment that doesn't exist."""
    sensors: list[FieldSensor] = []
    for well in config.wells:
        groups = (well.pad, well.id)
        sensors.append(
            FieldSensor(f"{well.id}.PT-WH", well.id, "AETHER_ONSHORE_GAS_WELL", "aether_well.tubing_head_pressure",
                        "pressure", "GAUGE", "Pa", "psi", PRESSURE_NOISE_PA, "NODE", f"{WELLHEAD_PREFIX}{well.id}", groups)
        )  # fmt: skip
        sensors.append(
            FieldSensor(f"{well.id}.FT", well.id, "AETHER_ONSHORE_GAS_WELL", "aether_well.gas_flow_rate",
                        "standard_volume_flow", "NOT_APPLICABLE", "sm3_per_s", "ksm3_per_d", FLOW_NOISE, "EDGE_FLOW", f"INFLOW:{well.id}", groups)
        )  # fmt: skip
    for junction in config.junctions:
        if junction.node_type.value == "JUNCTION":
            sensors.append(
                FieldSensor(f"{junction.id}.PT-NET", junction.id, "AETHER_GATHERING", "aether_gathering.header_pressure",
                            "pressure", "GAUGE", "Pa", "psi", PRESSURE_NOISE_PA, "NODE", junction.id, (str(junction.pad), junction.id))
            )  # fmt: skip
    sensors.append(
        FieldSensor("MANIFOLD.PT", "MANIFOLD", "AETHER_GATHERING", "aether_gathering.manifold_pressure",
                    "pressure", "GAUGE", "Pa", "psi", PRESSURE_NOISE_PA, "NODE", "MANIFOLD", ("MANIFOLD",))
    )  # fmt: skip
    pad_of = {j.id: j.pad for j in config.junctions}
    for segment in config.segments:
        pad = pad_of.get(segment.source)
        sensors.append(
            FieldSensor(f"{segment.id}.DPT-NET", segment.id, "AETHER_GATHERING", "aether_gathering.network_segment_differential_pressure",
                        "pressure", "DIFFERENTIAL", "Pa", "psi", DP_NOISE_PA, "DIFFERENTIAL", segment.id,
                        tuple(g for g in (pad, segment.id) if g))
        )  # fmt: skip
    sensors.append(
        FieldSensor("COMP-SUCTION.PT", "COMP-SUCTION", "AETHER_COMPRESSOR", "aether_compression.suction_pressure",
                    "pressure", "GAUGE", "Pa", "psi", PRESSURE_NOISE_PA, "NODE", "COMP-SUCTION", ("COMP-STATION",))
    )  # fmt: skip
    for unit in config.compression.units:
        sensors.append(
            FieldSensor(f"{unit.id}.FT", unit.id, "AETHER_COMPRESSOR", "aether_compression.unit_flow",
                        "standard_volume_flow", "NOT_APPLICABLE", "sm3_per_s", "ksm3_per_d", FLOW_NOISE, "EDGE_FLOW", unit.id, (unit.id, "COMP-STATION"))
        )  # fmt: skip
        sensors.append(
            FieldSensor(f"{unit.id}.STATE", unit.id, "AETHER_COMPRESSOR", "aether_compression.operating_state",
                        "discrete_state", "NOT_APPLICABLE", "state_code", "state_code", 0.0, "COMPRESSOR_STATE", unit.id, (unit.id, "COMP-STATION"))
        )  # fmt: skip
    return sensors


@dataclass(frozen=True)
class FieldRun:
    scenario: FieldScenario
    truth: pd.DataFrame
    telemetry: pd.DataFrame
    parameter_set_sha256: str
    simulator_name: str
    simulator_version: int
    seed: int

    @property
    def run_id(self) -> str:
        return f"{self.scenario.scenario_id}:v{self.scenario.version}:{self.scenario.case_name}"

    def canonical_sha256(self) -> str:
        return canonical_sha256(self.truth, self.telemetry)


def canonical_sha256(truth: pd.DataFrame, telemetry: pd.DataFrame) -> str:
    """Hash of values rounded well above solver and platform noise."""
    digest = hashlib.sha256()
    rounded = truth.drop(columns=[c for c in truth.columns if c.startswith("diag_")]).copy()
    for column in rounded.select_dtypes("number").columns:
        decimals = 5 if "_q_" in column or "flow" in column else 0 if "_p_" in column else 6
        rounded[column] = rounded[column].round(decimals)
    digest.update(rounded.to_csv(index=False, float_format="%.6f").encode())
    view = telemetry[
        ["offset_s", "tag", "value", "unit", "quality", "sensor_status", "equipment_state"]
    ].copy()
    for unit, decimals in _DECIMALS.items():
        mask = view["unit"] == unit
        view.loc[mask, "value"] = view.loc[mask, "value"].round(decimals)
    digest.update(view.to_csv(index=False, float_format="%.6f").encode())
    return digest.hexdigest()


def _tag_generator(seed: int, tag: str) -> np.random.Generator:
    """A stream fixed by seed and tag, so adding a sensor can't change another sensor's noise."""
    sequence = np.random.SeedSequence([seed, zlib.crc32(tag.encode())])
    return np.random.Generator(np.random.PCG64(sequence))


def _truth_frame(
    model: NetworkModel, scenario: FieldScenario, offsets: np.ndarray
) -> tuple[pd.DataFrame, list[NetworkSolution]]:
    cache: dict[NetworkState, NetworkSolution] = {}
    solutions = []
    for offset in offsets:
        state = scenario.state_at(int(offset))
        if state not in cache:
            cache[state] = solve_network(model, state)
        solutions.append(cache[state])
    graph = model.graph
    columns: dict[str, object] = {"offset_s": offsets}
    columns["truth_regime"] = [s.regime.value for s in solutions]
    columns["truth_total_flow"] = [s.total_flow for s in solutions]
    for node in graph.nodes.values():
        if node.node_type.value not in ("SITE", "RESERVOIR_BOUNDARY"):
            columns[f"truth_p_{node.node_id}"] = [
                s.pressure_pa_abs[node.node_id] for s in solutions
            ]
    for edge in graph.flow_edges():
        columns[f"truth_q_{edge.edge_id}"] = [
            s.edge_flow_sm3_per_s[edge.edge_id] for s in solutions
        ]
    for well in model.wells:
        columns[f"truth_status_{well}"] = [s.well_status[well].value for s in solutions]
    for unit in model.capacity:
        columns[f"truth_state_{unit}"] = [s.compressor_state[unit].value for s in solutions]
    columns["truth_fault_active"] = [
        scenario.first_onset_s is not None and int(o) >= scenario.first_onset_s for o in offsets
    ]
    # Segments always have a severity column. Another pipe gets one only when this run restricts it,
    # so runs without flowline restrictions keep exactly the truth table Gate 4 accepted.
    restricted = {
        f.asset_id
        for f in getattr(scenario, "physical_faults", ())
        if f.kind == "SEGMENT_RESTRICTION"
    }
    segments = [s.id for s in model.config.segments]
    for pipe in segments + sorted(restricted - set(segments)):
        columns[f"truth_severity_{pipe}"] = [
            dict(scenario.state_at(int(o)).severity).get(pipe, 0.0) for o in offsets
        ]
    for unit in model.capacity:
        columns[f"truth_capacity_fraction_{unit}"] = [
            dict(scenario.state_at(int(o)).compressor_fraction).get(unit, 1.0) for o in offsets
        ]
    columns["truth_closed_valves"] = [
        ",".join(sorted(scenario.state_at(int(o)).closed_valves)) for o in offsets
    ]
    columns["truth_max_mach"] = [max(s.mach.values(), default=0.0) for s in solutions]
    columns["truth_min_reynolds"] = [
        min(s.reynolds.values(), default=float("inf")) for s in solutions
    ]
    columns["diag_newton_iterations"] = [s.diagnostics.newton_iterations for s in solutions]
    columns["diag_active_set_passes"] = [s.diagnostics.active_set_passes for s in solutions]
    columns["diag_relative_residual"] = [s.diagnostics.max_relative_residual for s in solutions]
    return pd.DataFrame(columns), solutions


def _true_values(
    sensor: FieldSensor, truth: pd.DataFrame, model: NetworkModel, ambient: float
) -> np.ndarray:
    if sensor.source_kind == "NODE":
        return convert_pressure(
            truth[f"truth_p_{sensor.source_id}"].to_numpy(),
            ReferenceType.ABSOLUTE,
            ReferenceType.GAUGE,
            ambient_pa_abs=ambient,
        )
    if sensor.source_kind == "DIFFERENTIAL":
        edge = model.graph.edges[sensor.source_id]
        return (truth[f"truth_p_{edge.source}"] - truth[f"truth_p_{edge.target}"]).to_numpy()
    if sensor.source_kind == "EDGE_FLOW":
        return truth[f"truth_q_{sensor.source_id}"].to_numpy()
    state = truth[f"truth_state_{sensor.source_id}"]
    return state.map({k.value: v for k, v in COMPRESSOR_STATE_CODE.items()}).to_numpy(dtype=float)


def _equipment_state(sensor: FieldSensor, truth: pd.DataFrame, model: NetworkModel) -> np.ndarray:
    status = f"truth_status_{sensor.asset_id}"
    if status in truth:
        return truth[status].to_numpy()
    state = f"truth_state_{sensor.asset_id}"
    if state in truth:
        return truth[state].to_numpy()
    if sensor.asset_id in model.graph.edges:
        valve = model.graph.edges[sensor.asset_id].valve_asset_id
        closed = truth["truth_closed_valves"].str.split(",").map(lambda names: valve in names)
        return np.where(closed, "ISOLATED", "IN_SERVICE")
    regime = truth["truth_regime"]
    if sensor.asset_id == "COMP-SUCTION":
        return regime.to_numpy()
    return np.where(truth["truth_total_flow"] > 0, "IN_SERVICE", "NO_FLOW")


def _telemetry(
    scenario: FieldScenario,
    truth: pd.DataFrame,
    model: NetworkModel,
    sensors: list[FieldSensor],
    catalog: FieldCatalog,
    parameter_sha: str,
    run_id: str,
) -> pd.DataFrame:
    simulation = catalog.simulation
    ambient = model.config.ambient.pressure_pa_abs
    offsets = truth["offset_s"].to_numpy()
    clock = pd.Timestamp(simulation.simulated_epoch) + pd.to_timedelta(offsets, unit="s")
    times = clock.strftime("%Y-%m-%dT%H:%M:%SZ")
    frames = []
    for sensor in sensors:
        truth_values = _true_values(sensor, truth, model, ambient)
        noise = (
            _tag_generator(simulation.seed, sensor.tag).normal(0.0, 1.0, len(offsets))
            * sensor.noise_std
        )
        values = truth_values + noise
        if sensor.quantity == "standard_volume_flow":
            values = np.maximum(values, 0.0)
        for fault in scenario.sensor_faults:
            if fault.tag == sensor.tag:
                values = values + np.array([fault.error_at(int(o)) for o in offsets])
        quality = np.full(len(offsets), GOOD, dtype=object)
        status = np.full(len(offsets), OK, dtype=object)
        undetermined = np.isnan(truth_values)
        quality[undetermined], status[undetermined] = BAD_NOT_MEASURABLE, NOT_MEASURABLE
        for dropout in scenario.communication_faults:
            if dropout.group in sensor.groups:
                lost = (offsets >= dropout.onset_s) & (offsets < dropout.end_s)
                quality[lost], status[lost] = BAD_COMM, COMM_LOST
        values = np.where(quality == GOOD, values, np.nan)
        frames.append(
            pd.DataFrame(
                {
                    "offset_s": offsets,
                    "simulated_time": times,
                    "tag": sensor.tag,
                    "asset_id": sensor.asset_id,
                    "sensor_position": sensor.measurement_definition_id,
                    "value": values,
                    "unit": sensor.unit,
                    "reference": sensor.reference,
                    "quality": quality,
                    "sensor_status": status,
                    "equipment_state": _equipment_state(sensor, truth, model),
                }
            )
        )
    telemetry = pd.concat(frames, ignore_index=True)
    telemetry["provenance_class"] = PROVENANCE
    telemetry["scenario_id"] = scenario.scenario_id
    telemetry["scenario_run_id"] = run_id
    telemetry["simulator_version"] = model.config.network.version
    telemetry["parameter_set_sha256"] = parameter_sha
    return telemetry


@lru_cache(maxsize=1)
def default_setup() -> tuple[
    NetworkConfig, NetworkGraph, NetworkModel, FieldCatalog, tuple[FieldSensor, ...]
]:
    config = load_network()
    graph = build_graph(config)
    return (
        config,
        graph,
        NetworkModel(config, graph),
        load_catalog(),
        tuple(build_sensors(config, graph)),
    )


def simulate_field(scenario: FieldScenario) -> FieldRun:
    config, _, model, catalog, sensors = default_setup()
    simulation = catalog.simulation
    offsets = np.arange(0, simulation.duration_s, simulation.interval_s, dtype=np.int64)
    truth, _ = _truth_frame(model, scenario, offsets)
    parameter_sha = catalog.sha256(scenario, config.model_dump(mode="json", by_alias=True))
    run_id = f"{scenario.scenario_id}:v{scenario.version}:{scenario.case_name}"
    telemetry = _telemetry(scenario, truth, model, list(sensors), catalog, parameter_sha, run_id)
    return FieldRun(
        scenario,
        truth,
        telemetry,
        parameter_sha,
        config.network.name,
        config.network.version,
        simulation.seed,
    )


@lru_cache(maxsize=8)
def simulate_by_id(scenario_id: str) -> FieldRun:
    """One run per process, because several reports and tests read the same result."""
    return simulate_field(default_setup()[3].get(scenario_id))


CATEGORIES = tuple(Category)
