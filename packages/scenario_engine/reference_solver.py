"""An independent check on the Newton solver, using nested bisection and sharing none of its code.

It is slow, and it only handles a fixed suction pressure, so it exists for tests and reports.
"""

from __future__ import annotations

import yaml

from .config import ScenarioConfig, load_config
from .network_graph import NETWORK_PATH, NetworkConfig, NetworkGraph, build_graph
from .network_solver import NetworkModel

_STEPS = 44


def _bisect(function, low: float, high: float) -> float:
    """Root of a function that decreases from positive to negative."""
    for _ in range(_STEPS):
        middle = 0.5 * (low + high)
        if function(middle) > 0:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def _pipe_k(model: NetworkModel, edge_id: str, severity: dict[str, float]) -> float:
    return model.segment_resistance(model.graph.edges[edge_id], severity.get(edge_id, 0.0))


def _well_flow(model: NetworkModel, well: str, header: float) -> float:
    """Flow of one well into a header, from inflow and flowline in series."""
    spec = model.wells[well]
    available = spec.shut_in_pa_abs**2 - header**2
    if available <= 0:
        return 0.0
    k = _pipe_k(model, spec.flowline, {})

    def balance(q: float) -> float:
        return available - (q / spec.coefficient) ** (1.0 / model.exponent) - k * q**2

    return _bisect(balance, 0.0, spec.coefficient * available**model.exponent)


def _pad_flow(
    model: NetworkModel,
    graph: NetworkGraph,
    header: str,
    manifold: float,
    severity: dict[str, float],
) -> tuple[float, float]:
    """Flow and header pressure of one pad discharging into a manifold pressure."""
    wells = [w for w, s in model.wells.items() if graph.edges[s.flowline].target == header]
    segment = graph.downstream_edge(header)
    assert segment is not None
    k = _pipe_k(model, segment.edge_id, severity)

    def balance(p: float) -> float:
        return sum(_well_flow(model, w, p) for w in wells) - ((p**2 - manifold**2) / k) ** 0.5

    top = max(model.wells[w].shut_in_pa_abs for w in wells)
    pressure = _bisect(balance, manifold, top)
    return ((pressure**2 - manifold**2) / k) ** 0.5, pressure


def reference_solve(
    model: NetworkModel, suction_pa_abs: float, severity: dict[str, float] | None = None
) -> dict[str, float]:
    """Pressures and flows for all wells open, at a given suction pressure."""
    severity = severity or {}
    graph = model.graph
    headers = [j.id for j in model.config.junctions if j.node_type.value == "JUNCTION"]
    trunk = graph.downstream_edge("MANIFOLD")
    assert trunk is not None
    k = _pipe_k(model, trunk.edge_id, severity)

    def balance(p: float) -> float:
        return (
            sum(_pad_flow(model, graph, h, p, severity)[0] for h in headers)
            - ((p**2 - suction_pa_abs**2) / k) ** 0.5
        )

    top = min(s.shut_in_pa_abs for s in model.wells.values())
    manifold = _bisect(balance, suction_pa_abs, top)
    result = {"MANIFOLD": manifold, "total_flow": ((manifold**2 - suction_pa_abs**2) / k) ** 0.5}
    for header in headers:
        result[header] = _pad_flow(model, graph, header, manifold, severity)[1]
    return result


def single_well_network() -> tuple[NetworkModel, ScenarioConfig]:
    """The Gate 3 reference case as a network: one well and one segment into a fixed pressure."""
    gate3 = load_config()
    data = yaml.safe_load(NETWORK_PATH.read_text())
    data["gas"] = gate3.gas.model_dump()
    data["standard_conditions"] = gate3.standard_conditions.model_dump()
    data["pipes"] = {
        "darcy_friction_factor": gate3.gathering_segment.darcy_friction_factor,
        "restricted_length_m": gate3.gathering_segment.restricted_length_m,
    }
    data["well_defaults"]["deliverability_exponent"] = gate3.well.deliverability_exponent
    data["well_defaults"]["flowline_diameter_m"] = 1.0
    data["wells"] = [
        {
            "id": "A-03", "pad": "PAD-A", "flowline": "FL-A-03",
            "shut_in_pa_abs": gate3.well.shut_in_wellhead_pressure_pa_abs,
            "coefficient": gate3.well.deliverability_coefficient,
            "flowline_m": 1e-6, "x": 0, "y": 0,
        }
    ]  # fmt: skip
    data["junctions"] = [
        {"id": "HDR-A", "node_type": "JUNCTION", "pad": "PAD-A", "x": 0, "y": 0},
        {"id": "MANIFOLD", "node_type": "MANIFOLD", "x": 0, "y": 0},
        {"id": "COMP-SUCTION", "node_type": "SUCTION_HEADER", "x": 0, "y": 0},
        {"id": "COMP-DISCHARGE", "node_type": "DISCHARGE_BOUNDARY", "x": 0, "y": 0},
    ]
    data["segments"] = [
        {
            "id": "GS-A", "from": "HDR-A", "to": "MANIFOLD",
            "length_m": gate3.gathering_segment.length_m,
            "diameter_m": gate3.gathering_segment.internal_diameter_m, "isolation_valve": "IV-A",
        },
        {"id": "GS-TRUNK", "from": "MANIFOLD", "to": "COMP-SUCTION", "length_m": 1e-6, "diameter_m": 1.0, "isolation_valve": "IV-STATION"},
    ]  # fmt: skip
    data["compression"]["suction_setpoint_pa_abs"] = (
        gate3.gathering_segment.downstream_boundary_pressure_pa_abs
    )
    data["compression"]["reference_suction_pa_abs"] = (
        gate3.gathering_segment.downstream_boundary_pressure_pa_abs
    )
    data["compression"]["units"] = [{"id": "C-01", "capacity_sm3_per_s": 100.0}]
    data["sites"] = []
    config = NetworkConfig.model_validate(data)
    return NetworkModel(config, build_graph(config)), gate3
