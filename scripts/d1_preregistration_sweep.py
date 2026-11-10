"""Evidence for D1 preregistration version 4: impact and sensor detectability of each pipe's
restriction in the nominal Gate 4 model.

No D1 case is generated. The nominal network is solved once per pipe and severity, at the design well
parameters and suction setpoint, and compared with the unrestricted solution. Writes
reports/diagnostics/preregistration_sweep.json.
"""

from __future__ import annotations

import json

import numpy as np

from packages.scenario_engine.network_graph import REPO_ROOT, EdgeType, build_graph, load_network
from packages.scenario_engine.network_solver import NetworkModel, NetworkState, solve_network

OUT = REPO_ROOT / "reports" / "diagnostics" / "preregistration_sweep.json"
PRESSURE_NOISE_PA, DP_NOISE_PA, FLOW_NOISE = 2000.0, 500.0, 0.0015  # Gate 4 permanent sensors
SAMPLES = 24  # a 2-hour average of 5-minute samples


def main() -> int:
    config = load_network()
    graph = build_graph(config)
    model = NetworkModel(config, graph)
    base = solve_network(model, NetworkState())
    field = base.total_flow
    pipes = [
        e.edge_id
        for e in graph.edges.values()
        if e.edge_type in (EdgeType.FLOWLINE, EdgeType.GATHERING_SEGMENT)
    ]
    nodes = [
        n
        for n in base.pressure_pa_abs
        if n.startswith("WH:") or n in ("HDR-A", "HDR-B", "MANIFOLD", "COMP-SUCTION")
    ]
    segments = [
        e.edge_id for e in graph.edges.values() if e.edge_type is EdgeType.GATHERING_SEGMENT
    ]
    inflows = [e for e in base.edge_flow_sm3_per_s if e.startswith("INFLOW:")]

    def dp(solution, edge_id: str) -> float:
        edge = graph.edges[edge_id]
        return solution.pressure_pa_abs[edge.source] - solution.pressure_pa_abs[edge.target]

    def largest_shift(solution) -> float:
        """Largest change in any permanent sensor's 2-hour mean, in standard errors."""
        shifts = [
            abs(solution.pressure_pa_abs[n] - base.pressure_pa_abs[n])
            / (PRESSURE_NOISE_PA / np.sqrt(SAMPLES))
            for n in nodes
        ]
        shifts += [
            abs(dp(solution, s) - dp(base, s)) / (DP_NOISE_PA / np.sqrt(SAMPLES)) for s in segments
        ]
        shifts += [
            abs(solution.edge_flow_sm3_per_s[e] - base.edge_flow_sm3_per_s[e])
            / (FLOW_NOISE / np.sqrt(SAMPLES))
            for e in inflows
        ]
        return float(max(shifts))

    grid = np.round(np.arange(0.10, 0.70, 0.01), 2)
    rows = {}
    for pipe in pipes:
        impact, shift = [], []
        for severity in grid:
            solution = solve_network(model, NetworkState(severity=((pipe, float(severity)),)))
            impact.append((field - solution.total_flow) / field)
            shift.append(largest_shift(solution))
        impact_a, shift_a = np.array(impact), np.array(shift)

        def first(mask: np.ndarray) -> float | None:
            return float(grid[mask][0]) if mask.any() else None

        rows[pipe] = {
            "severity_where_impact_reaches_1pct": first(impact_a >= 0.01),
            "severity_where_impact_reaches_0p1pct": first(impact_a >= 0.001),
            "largest_sensor_shift_se_at": {
                f"{s:.2f}": round(float(shift_a[list(grid).index(s)]), 1)
                for s in (0.10, 0.30, 0.60)
            },
            "impact_share_at": {
                f"{s:.2f}": round(float(impact_a[list(grid).index(s)]), 5)
                for s in (0.10, 0.30, 0.60, 0.69)
            },
        }
    output = {
        "purpose": "Evidence for D1 preregistration version 4. Nominal model only; no D1 case generated.",
        "field_flow_sm3_per_s": round(field, 5),
        "noise": {
            "pressure_pa": PRESSURE_NOISE_PA,
            "dp_pa": DP_NOISE_PA,
            "flow_sm3_per_s": FLOW_NOISE,
            "samples_averaged": SAMPLES,
        },
        "severity_grid": [float(grid[0]), float(grid[-1]), 0.01],
        "pipes": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=2) + "\n")
    print(OUT.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
