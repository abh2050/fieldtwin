"""Coupled steady-state flow solve for the whole network at one instant.

The network is a tree, so the unknowns are well flows q. Each pipe's flow Q is the sum of the wells
above it, which makes mass balance at every junction exact by construction. For each flowing well:

    (q / C)^(1/n) + sum over its path of K Q^2 + x_suction(Q_total) = p_shut_in^2

    x_suction = p_setpoint^2                 while recycle holds suction at setpoint
    x_suction = (Q_total p_ref / capacity)^2 when the station is capacity-limited

All wells share each Q on their common path, so they can't disagree about a shared pressure. These
equations are the gradient of a convex function, so the solution is unique and damped Newton reaches
it. A well that can't flow leaves the active set, and re-enters if its header falls below shut-in.
Pressures then follow exactly by walking upstream from suction. Branches carrying no flow are
handled explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from .config import UNIVERSAL_GAS_CONSTANT
from .network_graph import (
    SOURCE_PREFIX,
    WELLHEAD_PREFIX,
    Edge,
    EdgeType,
    NetworkConfig,
    NetworkGraph,
    NodeType,
)

_ARMIJO = 1.0e-4
_MAX_BACKTRACKS = 60
_BOUNDARY_FRACTION = 0.1  # A step can remove at most 90% of a well's flow.
_ZERO_FLOW = 1.0e-9  # sm3/s. Below this a well has backed out.
UNDETERMINED = float("nan")


class SolverDidNotConverge(RuntimeError):
    """Newton failed to reach the residual tolerance. No result is returned."""


class InfeasibleNetworkState(ValueError):
    """The requested state has no physical solution inside the model's scope."""


class WellStatus(StrEnum):
    PRODUCING = "PRODUCING"
    SHUT_IN = "SHUT_IN"
    ISOLATED = "ISOLATED"
    BACKED_OUT = "BACKED_OUT"


class StationRegime(StrEnum):
    SETPOINT_CONTROLLED = "SETPOINT_CONTROLLED"
    CAPACITY_LIMITED = "CAPACITY_LIMITED"
    NO_FLOW = "NO_FLOW"
    STOPPED = "STOPPED"


class CompressorState(StrEnum):
    RUNNING = "RUNNING"
    DERATED = "DERATED"
    STOPPED = "STOPPED"


COMPRESSOR_STATE_CODE = {
    CompressorState.STOPPED: 0,
    CompressorState.DERATED: 1,
    CompressorState.RUNNING: 2,
}


@dataclass(frozen=True)
class NetworkState:
    """What is true at one instant. Every field is an operating condition, not a measurement."""

    severity: tuple[tuple[str, float], ...] = ()
    closed_valves: frozenset[str] = frozenset()
    shut_in_wells: frozenset[str] = frozenset()
    compressor_fraction: tuple[tuple[str, float], ...] = ()


@dataclass
class Diagnostics:
    newton_iterations: int = 0
    active_set_passes: int = 0
    max_relative_residual: float = 0.0
    converged: bool = True


@dataclass
class NetworkSolution:
    pressure_pa_abs: dict[str, float]
    edge_flow_sm3_per_s: dict[str, float]
    well_status: dict[str, WellStatus]
    regime: StationRegime
    compressor_state: dict[str, CompressorState]
    mach: dict[str, float]
    reynolds: dict[str, float]
    diagnostics: Diagnostics = field(default_factory=Diagnostics)

    @property
    def total_flow(self) -> float:
        return sum(q for edge, q in self.edge_flow_sm3_per_s.items() if edge.startswith("INFLOW:"))


def _required(value: float | None) -> float:
    if value is None:
        raise InfeasibleNetworkState("a pipe is missing its length or diameter")
    return value


class NetworkModel:
    """Physical coefficients for a validated graph. It holds no time-varying state."""

    def __init__(self, config: NetworkConfig, graph: NetworkGraph):
        self.config = config
        self.graph = graph
        gas, std = config.gas, config.standard_conditions
        self.rho_std = (
            std.pressure_pa_abs
            * gas.molar_mass_kg_per_mol
            / (UNIVERSAL_GAS_CONSTANT * std.temperature_k)
        )
        self.z_r_t = gas.compressibility_factor * gas.specific_gas_constant * gas.temperature_k
        self.wells = {w.id: w for w in config.wells}
        self.exponent = config.well_defaults.deliverability_exponent
        self.capacity = {u.id: u.capacity_sm3_per_s for u in config.compression.units}
        self.suction = next(
            n.node_id for n in graph.nodes.values() if n.node_type is NodeType.SUCTION_HEADER
        )
        self.discharge = next(
            n.node_id for n in graph.nodes.values() if n.node_type is NodeType.DISCHARGE_BOUNDARY
        )
        self.pipes = [
            e
            for e in graph.flow_edges()
            if e.edge_type in (EdgeType.FLOWLINE, EdgeType.GATHERING_SEGMENT)
        ]
        self.pipe_k_per_length = {
            e.edge_id: 16.0
            * config.pipes.darcy_friction_factor
            * self.z_r_t
            / (np.pi**2 * _required(e.diameter_m) ** 5)
            for e in self.pipes
        }

    def segment_resistance(self, edge: Edge, severity: float) -> float:
        """K(s) in Pa^2 per (sm3/s)^2, for one pipe with an optional restriction."""
        limit = self.config.validity_envelope.severity_limit
        if severity < 0 or severity > limit:
            raise InfeasibleNetworkState(
                f"severity {severity} on {edge.edge_id} is outside 0 to {limit}"
            )
        length = _required(edge.length_m)
        if severity == 0:
            equivalent = length
        else:
            restricted = self.config.pipes.restricted_length_m
            equivalent = (length - restricted) + restricted / (1.0 - severity) ** 5
        return self.pipe_k_per_length[edge.edge_id] * equivalent * self.rho_std**2


@dataclass
class _Flows:
    """The equations for a set of wells that flow."""

    wells: list[str]
    pipes: list[Edge]
    incidence: np.ndarray  # pipes by wells: 1 where a well's gas passes through a pipe.
    resistance: np.ndarray
    source_x: np.ndarray
    coefficient: np.ndarray
    power: float  # 1 / n
    suction_x: float | None
    station_a: float  # (p_ref / capacity)^2, used when suction floats.

    def residual(self, q: np.ndarray) -> np.ndarray:
        pipe_flow = self.incidence @ q
        value = (q / self.coefficient) ** self.power
        value = value + self.incidence.T @ (self.resistance * pipe_flow**2)
        return value + self._suction_x(q) - self.source_x

    def _suction_x(self, q: np.ndarray) -> float:
        return (
            self.suction_x if self.suction_x is not None else self.station_a * float(q.sum()) ** 2
        )

    def jacobian(self, q: np.ndarray) -> np.ndarray:
        pipe_flow = self.incidence @ q
        slope = self.power * (q / self.coefficient) ** (self.power - 1.0) / self.coefficient
        matrix = (
            np.diag(slope)
            + self.incidence.T @ np.diag(2.0 * self.resistance * pipe_flow) @ self.incidence
        )
        if self.suction_x is None:
            matrix = matrix + 2.0 * self.station_a * float(q.sum())
        return matrix

    def potential(self, q: np.ndarray) -> float:
        """The convex function whose gradient is the residual."""
        pipe_flow = self.incidence @ q
        value = float(
            np.sum(
                self.coefficient * (q / self.coefficient) ** (self.power + 1.0) / (self.power + 1.0)
            )
        )
        value += float(np.sum(self.resistance * pipe_flow**3)) / 3.0
        total = float(q.sum())
        value += (
            self.suction_x * total
            if self.suction_x is not None
            else self.station_a * total**3 / 3.0
        )
        return value - float(self.source_x @ q)


def _path(model: NetworkModel, well: str) -> list[Edge]:
    edges: list[Edge] = []
    node = f"{WELLHEAD_PREFIX}{well}"
    # A validated graph is a tree, so this limit can only trip on a corrupted graph.
    for _ in range(len(model.graph.nodes)):
        if node == model.suction:
            return edges
        edge = model.graph.downstream_edge(node)
        if edge is None:
            raise InfeasibleNetworkState(f"{well} has no path to suction")
        edges.append(edge)
        node = edge.target
    raise InfeasibleNetworkState(f"{well}: the path to suction didn't end")


def _build_flows(
    model: NetworkModel,
    wells: list[str],
    severity: dict[str, float],
    suction_x: float | None,
    capacity: float,
) -> _Flows:
    paths = {w: _path(model, w) for w in wells}
    pipes: dict[str, Edge] = {}
    for path in paths.values():
        for edge in path:
            pipes.setdefault(edge.edge_id, edge)
    order = list(pipes)
    incidence = np.zeros((len(order), len(wells)))
    for column, well in enumerate(wells):
        for edge in paths[well]:
            incidence[order.index(edge.edge_id), column] = 1.0
    reference = model.config.compression.reference_suction_pa_abs
    return _Flows(
        wells,
        list(pipes.values()),
        incidence,
        np.array([model.segment_resistance(pipes[e], severity.get(e, 0.0)) for e in order]),
        np.array([model.wells[w].shut_in_pa_abs ** 2 for w in wells]),
        np.array([model.wells[w].coefficient for w in wells]),
        1.0 / model.exponent,
        suction_x,
        (reference / capacity) ** 2 if suction_x is None else 0.0,
    )


def _newton(
    flows: _Flows, tolerance: float, max_iterations: int
) -> tuple[np.ndarray, list[str], int, float]:
    """Damped Newton in well flows. Returns flows, wells that hit zero, iterations, and the residual."""
    scale = float(flows.source_x.max())
    floor = flows.suction_x if flows.suction_x is not None else 0.0
    available = np.maximum(flows.source_x - floor, 0.0)
    q = 0.5 * flows.coefficient * available ** (1.0 / flows.power)
    residual = flows.residual(q)
    for iteration in range(1, max_iterations + 1):
        worst = float(np.max(np.abs(residual))) / scale
        if worst < tolerance:
            return q, [], iteration - 1, worst
        matrix = flows.jacobian(q)
        diagonal = np.sqrt(np.diag(matrix))
        step = (
            np.linalg.solve(matrix / np.outer(diagonal, diagonal), -residual / diagonal) / diagonal
        )
        # Stay positive, since the laws only hold for forward flow.
        shrinking = step < 0
        factor = 1.0
        if shrinking.any():
            factor = min(
                1.0, float(np.min(-(1.0 - _BOUNDARY_FRACTION) * q[shrinking] / step[shrinking]))
            )
        energy = flows.potential(q)
        slope = float(residual @ step)
        for _ in range(_MAX_BACKTRACKS):
            candidate = q + factor * step
            new_residual = flows.residual(candidate)
            # Near the solution, the potential's change falls below floating-point precision, so a
            # step that reduces the residual is also accepted.
            reduced = np.max(np.abs(new_residual)) < np.max(np.abs(residual))
            if flows.potential(candidate) <= energy + _ARMIJO * factor * slope or reduced:
                break
            factor *= 0.5
        q, residual = candidate, new_residual
        vanished = [w for w, value in zip(flows.wells, q, strict=True) if value < _ZERO_FLOW]
        if vanished:
            return q, vanished, iteration, float(np.max(np.abs(residual))) / scale
    final = float(np.max(np.abs(residual))) / scale
    if final < tolerance:
        return q, [], max_iterations, final
    raise SolverDidNotConverge(f"relative residual {final:.3e} after {max_iterations} iterations")


def _pressures_from_flows(
    model: NetworkModel, flows: _Flows, q: np.ndarray
) -> tuple[dict[str, float], dict[str, float]]:
    """Walk upstream from suction, so every shared node has exactly one pressure."""
    pipe_flow = flows.incidence @ q
    edge_flow = {f"INFLOW:{w}": float(v) for w, v in zip(flows.wells, q, strict=True)}
    edge_flow.update({e.edge_id: float(v) for e, v in zip(flows.pipes, pipe_flow, strict=True)})
    suction_x = (
        flows.suction_x if flows.suction_x is not None else flows.station_a * float(q.sum()) ** 2
    )
    pressure_x = {model.suction: suction_x}
    remaining = list(zip(flows.pipes, flows.resistance, pipe_flow, strict=True))
    while remaining:
        progressed = False
        for item in list(remaining):
            edge, resistance, flow = item
            if edge.target in pressure_x:
                pressure_x[edge.source] = pressure_x[edge.target] + resistance * flow**2
                remaining.remove(item)
                progressed = True
        if not progressed:
            raise InfeasibleNetworkState("the active network isn't connected to suction")
    return {n: float(np.sqrt(x)) for n, x in pressure_x.items()}, edge_flow


def _solve_active(
    model: NetworkModel,
    wells: list[str],
    severity: dict[str, float],
    suction_x: float | None,
    capacity: float,
    diagnostics: Diagnostics,
) -> tuple[list[str], dict[str, float], dict[str, float]]:
    """Find the flowing wells and their solution. A well that can't flow gets a check-valve zero."""
    settings = model.config.solver
    floor = suction_x if suction_x is not None else 0.0
    active = [w for w in wells if model.wells[w].shut_in_pa_abs ** 2 > floor]
    for _ in range(settings.max_active_set_passes):
        diagnostics.active_set_passes += 1
        if not active:
            return [], {}, {}
        flows = _build_flows(model, active, severity, suction_x, capacity)
        q, vanished, iterations, residual = _newton(
            flows, settings.relative_residual_tolerance, settings.max_iterations
        )
        diagnostics.newton_iterations += iterations
        if vanished:
            active = [w for w in active if w not in vanished]
            continue
        diagnostics.max_relative_residual = max(diagnostics.max_relative_residual, residual)
        pressures, edge_flow = _pressures_from_flows(model, flows, q)
        # A well left out may flow again if its header has fallen below its shut-in pressure.
        returning = [
            w
            for w in wells
            if w not in active
            and model.wells[w].shut_in_pa_abs > _header_pressure(model, w, pressures)
        ]
        if not returning:
            return active, pressures, edge_flow
        active = [w for w in wells if w in active or w in returning]
    raise SolverDidNotConverge("the set of flowing wells did not settle")


def _header_pressure(model: NetworkModel, well: str, pressures: dict[str, float]) -> float:
    """The nearest solved pressure downstream of a well that isn't flowing."""
    for edge in _path(model, well):
        if edge.target in pressures:
            return pressures[edge.target]
    return pressures[model.suction]


def solve_network(model: NetworkModel, state: NetworkState) -> NetworkSolution:
    """Solve one instant. Raises if infeasible or unconverged, and never returns a partial result."""
    graph, config = model.graph, model.config
    compression = config.compression
    if compression.discharge_pa_abs <= compression.suction_setpoint_pa_abs:
        raise InfeasibleNetworkState("discharge pressure must exceed the suction setpoint")
    severity = dict(state.severity)
    fractions = dict(state.compressor_fraction)
    for edge_id in severity:
        if (
            edge_id not in graph.edges
            or graph.edges[edge_id].edge_type is not EdgeType.GATHERING_SEGMENT
        ):
            raise InfeasibleNetworkState(f"{edge_id} is not a gathering segment")
    unknown_wells = state.shut_in_wells - set(model.wells)
    if unknown_wells:
        raise InfeasibleNetworkState(f"unknown wells: {sorted(unknown_wells)}")
    for unit, fraction in fractions.items():
        if unit not in model.capacity:
            raise InfeasibleNetworkState(f"{unit} is not a compressor")
        if fraction < 0 or fraction > 1:
            raise InfeasibleNetworkState(f"{unit} capacity fraction {fraction} is outside 0 to 1")
    valves = {e.valve_asset_id for e in graph.edges.values() if e.valve_asset_id}
    if state.closed_valves - valves:
        raise InfeasibleNetworkState(f"unknown valves: {sorted(state.closed_valves - valves)}")

    unit_capacity = {u: model.capacity[u] * fractions.get(u, 1.0) for u in model.capacity}
    station_capacity = sum(unit_capacity.values())
    compressor_state = {
        u: CompressorState.STOPPED
        if fractions.get(u, 1.0) == 0
        else CompressorState.DERATED
        if fractions.get(u, 1.0) < 1
        else CompressorState.RUNNING
        for u in model.capacity
    }
    open_wells = [w for w in model.wells if w not in state.shut_in_wells]
    connected = [w for w in open_wells if _reaches_suction(model, w, state.closed_valves)]
    station_open = station_capacity > 0
    flowing_candidates = connected if station_open else []
    diagnostics = Diagnostics()
    setpoint_x = compression.suction_setpoint_pa_abs**2

    active, pressures, flows = _solve_active(
        model, flowing_candidates, severity, setpoint_x, station_capacity, diagnostics
    )
    regime = StationRegime.SETPOINT_CONTROLLED if active else StationRegime.NO_FLOW
    arrivals = sum(q for e, q in flows.items() if e.startswith("INFLOW:"))
    if active and arrivals > station_capacity:
        # The station can't hold setpoint, so suction floats up until flow and capacity agree.
        active, pressures, flows = _solve_active(
            model, flowing_candidates, severity, None, station_capacity, diagnostics
        )
        regime = StationRegime.CAPACITY_LIMITED
    if not station_open:
        regime = StationRegime.STOPPED

    node_pressure, statuses = _complete_static_pressures(
        model, state, active, pressures, connected, station_open
    )
    edge_flow = {e.edge_id: 0.0 for e in graph.flow_edges()}
    edge_flow.update(flows)
    total = sum(q for e, q in edge_flow.items() if e.startswith("INFLOW:"))
    if station_capacity > 0:
        for unit, capacity in unit_capacity.items():
            edge_flow[unit] = total * capacity / station_capacity

    suction_pressure = node_pressure.get(model.suction, UNDETERMINED)
    if active and compression.discharge_pa_abs <= suction_pressure:
        raise InfeasibleNetworkState(
            f"suction {suction_pressure:.0f} Pa reached discharge {compression.discharge_pa_abs:.0f} Pa"
        )
    node_pressure[model.discharge] = compression.discharge_pa_abs
    mach, reynolds = _flow_regime(model, severity, edge_flow, node_pressure)
    return NetworkSolution(
        node_pressure, edge_flow, statuses, regime, compressor_state, mach, reynolds, diagnostics
    )


def _reaches_suction(model: NetworkModel, well: str, closed: frozenset[str]) -> bool:
    node = f"{WELLHEAD_PREFIX}{well}"
    for _ in range(len(model.graph.nodes)):
        if node == model.suction:
            return True
        edge = model.graph.downstream_edge(node)
        if edge is None or (edge.valve_asset_id and edge.valve_asset_id in closed):
            return False
        node = edge.target
    raise InfeasibleNetworkState(f"{well}: the path to suction didn't end")


def _connected_sections(model: NetworkModel, closed: frozenset[str]) -> list[set[str]]:
    """Groups of junctions joined by pipes whose valves are open. Gas can equalize inside a group."""
    junctions = {
        n.node_id
        for n in model.graph.nodes.values()
        if n.node_type in (NodeType.JUNCTION, NodeType.MANIFOLD, NodeType.SUCTION_HEADER)
    }
    sections = [{j} for j in junctions]
    for edge in model.graph.flow_edges():
        if edge.edge_type is not EdgeType.GATHERING_SEGMENT or edge.valve_asset_id in closed:
            continue
        first = next(s for s in sections if edge.source in s)
        second = next(s for s in sections if edge.target in s)
        if first is not second:
            first |= second
            sections.remove(second)
    return sections


def _complete_static_pressures(
    model: NetworkModel,
    state: NetworkState,
    active: list[str],
    solved: dict[str, float],
    connected: list[str],
    station_open: bool,
) -> tuple[dict[str, float], dict[str, WellStatus]]:
    """Set pressures where nothing flows, from what is physically connected to what.

    Gas in a connected section with no flow is static, so one pressure applies throughout, except
    across a flowing part that has already been solved. In order of precedence, a section takes:
    a solved downstream pressure, its highest open well's shut-in pressure (check valves stop gas
    returning to the reservoir), or the running station's setpoint. A closed section with no
    pressure source is undetermined, and it's reported that way, not given an invented value.
    """
    graph = model.graph
    pressure = dict(solved)
    statuses: dict[str, WellStatus] = {}
    closed = state.closed_valves
    if station_open and model.suction not in pressure:
        pressure[model.suction] = model.config.compression.suction_setpoint_pa_abs

    for section in _connected_sections(model, closed):
        unsolved = [n for n in section if n not in pressure]
        if not unsolved:
            continue
        if len(unsolved) < len(section):
            # Part of this section is solved, so a branch with no live flow reads what's downstream.
            pending = sorted(unsolved)
            for _ in range(len(pending) + 1):
                for node_id in list(pending):
                    edge = graph.downstream_edge(node_id)
                    if edge is not None and edge.target in pressure:
                        pressure[node_id] = pressure[edge.target]
                        pending.remove(node_id)
            if pending:
                raise InfeasibleNetworkState(f"no pressure can be assigned to {pending}")
            continue
        sources = [
            spec.shut_in_pa_abs
            for well, spec in model.wells.items()
            if well not in state.shut_in_wells and graph.edges[spec.flowline].target in section
        ]
        for node_id in section:
            pressure[node_id] = max(sources) if sources else UNDETERMINED

    for well, spec in model.wells.items():
        node = f"{WELLHEAD_PREFIX}{well}"
        edge = graph.downstream_edge(node)
        assert edge is not None
        header = pressure[edge.target]
        if well in active:
            statuses[well] = WellStatus.PRODUCING
        elif well in state.shut_in_wells:
            # The wing valve is closed, so the wellhead sensor sees the well's own shut-in pressure.
            statuses[well] = WellStatus.SHUT_IN
            pressure[node] = spec.shut_in_pa_abs
        elif well in connected and station_open:
            # Connected and open but not flowing: the header is above this well's shut-in pressure.
            statuses[well] = WellStatus.BACKED_OUT
            pressure[node] = header
        else:
            statuses[well] = WellStatus.ISOLATED
            pressure[node] = (
                spec.shut_in_pa_abs if np.isnan(header) else max(header, spec.shut_in_pa_abs)
            )
    return pressure, statuses


def _flow_regime(
    model: NetworkModel,
    severity: dict[str, float],
    edge_flow: dict[str, float],
    pressure: dict[str, float],
) -> tuple[dict[str, float], dict[str, float]]:
    """Mach and Reynolds at each flowing pipe's narrowest point, at its lowest pressure."""
    gas = model.config.gas
    sound = np.sqrt(gas.heat_capacity_ratio * model.z_r_t)
    mach, reynolds = {}, {}
    for edge in model.pipes:
        flow = edge_flow.get(edge.edge_id, 0.0)
        if flow <= 0:
            continue
        diameter = _required(edge.diameter_m) * (1.0 - severity.get(edge.edge_id, 0.0))
        area = np.pi * diameter**2 / 4.0
        density = pressure[edge.target] / model.z_r_t
        mass = model.rho_std * flow
        velocity = mass / (density * area)
        mach[edge.edge_id] = float(velocity / sound)
        reynolds[edge.edge_id] = float(density * velocity * diameter / gas.dynamic_viscosity_pa_s)
    return mach, reynolds


__all__ = [
    "COMPRESSOR_STATE_CODE",
    "CompressorState",
    "Diagnostics",
    "InfeasibleNetworkState",
    "NetworkModel",
    "NetworkSolution",
    "NetworkState",
    "SOURCE_PREFIX",
    "SolverDidNotConverge",
    "StationRegime",
    "UNDETERMINED",
    "WellStatus",
    "solve_network",
]
