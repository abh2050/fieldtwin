"""The network model as a diagnosis sees it: design values, calibrated wells, and measured boundaries.

This module may read the network design (config/facility/aether_network.yaml) and use the Gate 4
solver. It never imports the case generator, the simulation layer, or any truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np

from packages.scenario_engine.network_graph import (
    EdgeType,
    NetworkConfig,
    NetworkGraph,
    build_graph,
    load_network,
)
from packages.scenario_engine.network_solver import (
    NetworkModel,
    NetworkSolution,
    NetworkState,
    solve_network,
)

# Declared noise of the permanent sensors (docs/product/d1_diagnostic_spec.md).
PRESSURE_NOISE_PA = 2000.0
DP_NOISE_PA = 500.0
FLOW_NOISE_SM3_PER_S = 0.0015


@dataclass(frozen=True)
class Sensor:
    tag: str
    kind: str  # PRESSURE (gauge at a node), DP (across a segment), FLOW (on an edge)
    source: str
    noise: float


def sensors(config: NetworkConfig, graph: NetworkGraph) -> list[Sensor]:
    """The permanent instruments, derived from the network the same way Gate 4 derives them."""
    found: list[Sensor] = []
    for well in config.wells:
        found.append(Sensor(f"{well.id}.PT-WH", "PRESSURE", f"WH:{well.id}", PRESSURE_NOISE_PA))
        found.append(Sensor(f"{well.id}.FT", "FLOW", f"INFLOW:{well.id}", FLOW_NOISE_SM3_PER_S))
    for junction in config.junctions:
        if junction.node_type.value == "JUNCTION":
            found.append(
                Sensor(f"{junction.id}.PT-NET", "PRESSURE", junction.id, PRESSURE_NOISE_PA)
            )
    found.append(Sensor("MANIFOLD.PT", "PRESSURE", "MANIFOLD", PRESSURE_NOISE_PA))
    for segment in config.segments:
        found.append(Sensor(f"{segment.id}.DPT-NET", "DP", segment.id, DP_NOISE_PA))
    found.append(Sensor("COMP-SUCTION.PT", "PRESSURE", "COMP-SUCTION", PRESSURE_NOISE_PA))
    for unit in config.compression.units:
        found.append(Sensor(f"{unit.id}.FT", "FLOW", unit.id, FLOW_NOISE_SM3_PER_S))
    return found


class Forward:
    """Solve the network for one hypothesis at the case's calibrated operating point."""

    def __init__(
        self,
        multipliers: dict[str, float],
        suction_pa_abs: float,
        shut_in: frozenset[str] = frozenset(),
    ):
        self.design = load_network()
        self.graph = build_graph(self.design)
        wells = [
            w.model_copy(update={"coefficient": w.coefficient * multipliers.get(w.id, 1.0)})
            for w in self.design.wells
        ]
        compression = self.design.compression.model_copy(
            update={"suction_setpoint_pa_abs": suction_pa_abs}
        )
        self.config = self.design.model_copy(update={"wells": wells, "compression": compression})
        self.model = NetworkModel(self.config, self.graph)
        self.shut_in = shut_in
        self.ambient = self.config.ambient.pressure_pa_abs
        self._cache: dict[tuple, NetworkSolution] = {}

    @cached_property
    def pipes(self) -> list[str]:
        return sorted(
            e.edge_id
            for e in self.graph.edges.values()
            if e.edge_type in (EdgeType.FLOWLINE, EdgeType.GATHERING_SEGMENT)
        )

    def solve(
        self, pipe: str | None, severity: float, extra_shut_in: str | None = None
    ) -> NetworkSolution:
        key = (pipe, round(severity, 6), extra_shut_in)
        if key not in self._cache:
            shut = self.shut_in | ({extra_shut_in} if extra_shut_in else set())
            state = NetworkState(
                severity=((pipe, severity),) if pipe and severity > 0 else (),
                shut_in_wells=frozenset(shut),
            )
            self._cache[key] = solve_network(self.model, state)
        return self._cache[key]

    def read(self, solution: NetworkSolution, sensor: Sensor) -> float:
        if sensor.kind == "PRESSURE":
            return solution.pressure_pa_abs[sensor.source] - self.ambient
        if sensor.kind == "DP":
            edge = self.graph.edges[sensor.source]
            return solution.pressure_pa_abs[edge.source] - solution.pressure_pa_abs[edge.target]
        return solution.edge_flow_sm3_per_s[sensor.source]

    def vector(self, solution: NetworkSolution, chosen: list[Sensor]) -> np.ndarray:
        return np.array([self.read(solution, s) for s in chosen])

    def pipe_dp(self, solution: NetworkSolution, pipe: str) -> float:
        edge = self.graph.edges[pipe]
        return solution.pressure_pa_abs[edge.source] - solution.pressure_pa_abs[edge.target]


def calibrate_wells(
    design: NetworkConfig, flows: dict[str, float], wellhead_gauge: dict[str, float]
) -> dict[str, float]:
    """Each well's deliverability multiplier from a healthy window: q = C m (p_s^2 - p_wh^2)^n."""
    ambient = design.ambient.pressure_pa_abs
    exponent = design.well_defaults.deliverability_exponent
    multipliers = {}
    for well in design.wells:
        q, p = flows.get(well.id), wellhead_gauge.get(well.id)
        if q is None or p is None or not np.isfinite(q) or not np.isfinite(p) or q <= 0:
            multipliers[well.id] = 1.0
            continue
        drawdown = well.shut_in_pa_abs**2 - (p + ambient) ** 2
        multipliers[well.id] = (
            float(q / (well.coefficient * drawdown**exponent)) if drawdown > 0 else 1.0
        )
    return multipliers
