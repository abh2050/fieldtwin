"""The coupled solver: conservation, independent agreement, regression, and edge cases."""

from __future__ import annotations

import math

import numpy as np
import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from packages.scenario_engine import physics
from packages.scenario_engine.network_graph import (
    NETWORK_PATH,
    EdgeType,
    NetworkConfig,
    NodeType,
    build_graph,
    load_network,
)
from packages.scenario_engine.network_solver import (
    InfeasibleNetworkState,
    NetworkModel,
    NetworkState,
    SolverDidNotConverge,
    StationRegime,
    WellStatus,
    solve_network,
)
from packages.scenario_engine.reference_solver import reference_solve, single_well_network

CONFIG = load_network()
GRAPH = build_graph(CONFIG)
MODEL = NetworkModel(CONFIG, GRAPH)
WELLS = sorted(MODEL.wells)
UNITS = sorted(MODEL.capacity)
PROFILE = settings(
    max_examples=200, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)

states = st.builds(
    lambda a, b, trunk, valves, wells, fractions: NetworkState(
        tuple((k, v) for k, v in (("GS-A", a), ("GS-B", b), ("GS-TRUNK", trunk)) if v > 0),
        frozenset(valves),
        frozenset(wells),
        tuple(sorted(fractions.items())),
    ),
    st.sampled_from([0.0, 0.2, 0.4, 0.55, 0.65, 0.7]),
    st.sampled_from([0.0, 0.3, 0.6]),
    st.sampled_from([0.0, 0.4]),
    st.sets(st.sampled_from(["IV-A", "IV-B", "IV-STATION"]), max_size=3),
    st.sets(st.sampled_from(WELLS), max_size=12),
    st.dictionaries(st.sampled_from(UNITS), st.sampled_from([0.0, 0.1, 0.5, 0.9]), max_size=4),
)


def balance(solution, node_id, model=MODEL):
    total = 0.0
    for edge in model.graph.flow_edges():
        if edge.target == node_id:
            total += solution.edge_flow_sm3_per_s[edge.edge_id]
        if edge.source == node_id:
            total -= solution.edge_flow_sm3_per_s[edge.edge_id]
    return total


FREE_NODES = [
    n.node_id
    for n in GRAPH.nodes.values()
    if n.node_type
    in (NodeType.WELLHEAD, NodeType.JUNCTION, NodeType.MANIFOLD, NodeType.SUCTION_HEADER)
]


@PROFILE
@given(states)
def test_mass_balances_at_every_junction_in_any_state(state):
    solution = solve_network(MODEL, state)
    assert all(abs(balance(solution, n)) < 1e-8 for n in FREE_NODES)
    assert solution.diagnostics.max_relative_residual <= 1e-12


@PROFILE
@given(states)
def test_no_reverse_flow_and_pressure_falls_along_flow_in_any_state(state):
    solution = solve_network(MODEL, state)
    assert min(solution.edge_flow_sm3_per_s.values()) >= 0
    for edge in GRAPH.flow_edges():
        if (
            edge.edge_type in (EdgeType.FLOWLINE, EdgeType.GATHERING_SEGMENT)
            and solution.edge_flow_sm3_per_s[edge.edge_id] > 0
        ):
            assert solution.pressure_pa_abs[edge.source] > solution.pressure_pa_abs[edge.target]


@PROFILE
@given(states)
def test_each_well_state_and_flow_agree_in_any_state(state):
    solution = solve_network(MODEL, state)
    for well, spec in MODEL.wells.items():
        flow = solution.edge_flow_sm3_per_s[f"INFLOW:{well}"]
        assert (flow > 0) == (solution.well_status[well] is WellStatus.PRODUCING)
        if flow > 0:
            assert solution.pressure_pa_abs[f"WH:{well}"] < spec.shut_in_pa_abs


@PROFILE
@given(states)
def test_station_never_exceeds_capacity_or_falls_below_setpoint(state):
    solution = solve_network(MODEL, state)
    suction = solution.pressure_pa_abs["COMP-SUCTION"]
    fractions = dict(state.compressor_fraction)
    capacity = sum(MODEL.capacity[u] * fractions.get(u, 1.0) for u in UNITS)
    assert solution.total_flow <= capacity * max(suction, 1.6e6) / 1.6e6 + 1e-8
    if capacity > 0:
        assert suction >= 1.6e6 - 1e-3


@PROFILE
@given(states)
def test_same_state_gives_exactly_the_same_answer(state):
    first, second = solve_network(MODEL, state), solve_network(MODEL, state)
    assert first.edge_flow_sm3_per_s == second.edge_flow_sm3_per_s
    assert all(
        a == b or (math.isnan(a) and math.isnan(b))
        for a, b in zip(
            first.pressure_pa_abs.values(), second.pressure_pa_abs.values(), strict=True
        )
    )


@PROFILE
@given(st.floats(0.0, 0.69), st.floats(0.001, 0.01))
def test_more_restriction_moves_coupled_assets_in_the_right_direction(severity, extra):
    low = solve_network(MODEL, NetworkState((("GS-A", severity),)))
    high = solve_network(MODEL, NetworkState((("GS-A", severity + extra),)))
    q_low, q_high = low.edge_flow_sm3_per_s, high.edge_flow_sm3_per_s
    assert q_high["GS-A"] <= q_low["GS-A"] + 1e-9
    assert q_high["GS-B"] >= q_low["GS-B"] - 1e-9
    assert high.pressure_pa_abs["HDR-A"] >= low.pressure_pa_abs["HDR-A"] - 1e-3
    assert high.pressure_pa_abs["MANIFOLD"] <= low.pressure_pa_abs["MANIFOLD"] + 1e-3


# Coupling


def test_wells_share_one_solved_pressure_at_their_header():
    """Each flowline's inlet and resistance must imply the same header pressure for every well."""
    solution = solve_network(MODEL, NetworkState())
    header = solution.pressure_pa_abs["HDR-A"]
    for well in [w for w in CONFIG.wells if w.pad == "PAD-A"]:
        edge = GRAPH.edges[well.flowline]
        k = MODEL.segment_resistance(edge, 0.0)
        flow = solution.edge_flow_sm3_per_s[well.flowline]
        implied = math.sqrt(solution.pressure_pa_abs[f"WH:{well.id}"] ** 2 - k * flow**2)
        assert implied == pytest.approx(header, abs=1e-3)


def test_solved_pressure_is_not_what_independent_wells_would_give():
    """A lone well sees less backpressure, so independent simulators would overstate flow."""
    together = solve_network(MODEL, NetworkState()).edge_flow_sm3_per_s["INFLOW:A-03"]
    others = frozenset(WELLS) - {"A-03"}
    alone = solve_network(MODEL, NetworkState(shut_in_wells=others)).edge_flow_sm3_per_s[
        "INFLOW:A-03"
    ]
    assert alone > together * 1.01


@pytest.mark.parametrize(
    ("label", "severity"),
    [("open", {}), ("restricted", {"GS-A": 0.65}), ("both", {"GS-A": 0.5, "GS-B": 0.3})],
)
def test_newton_agrees_with_independent_nested_bisection(label, severity):
    solved = solve_network(MODEL, NetworkState(tuple(severity.items())))
    reference = reference_solve(MODEL, 1.6e6, severity)
    assert solved.total_flow == pytest.approx(reference["total_flow"], rel=1e-6), label
    for node in ("MANIFOLD", "HDR-A", "HDR-B"):
        assert solved.pressure_pa_abs[node] == pytest.approx(reference[node], abs=5.0)


def test_capacity_limited_solution_agrees_with_bisection_at_its_suction():
    solved = solve_network(MODEL, NetworkState(compressor_fraction=(("C-01", 0.1), ("C-02", 0.2))))
    assert solved.regime is StationRegime.CAPACITY_LIMITED
    suction = solved.pressure_pa_abs["COMP-SUCTION"]
    reference = reference_solve(MODEL, suction)
    assert solved.total_flow == pytest.approx(reference["total_flow"], rel=1e-6)
    capacity = 2.1 * (0.1 + 0.2 + 1 + 1)
    assert solved.total_flow == pytest.approx(capacity * suction / 1.6e6, rel=1e-9)


# Regression against Gate 3


@pytest.mark.parametrize("severity", [0.0, 0.1, 0.275, 0.45, 0.55, 0.7])
def test_network_reduces_to_the_gate_3_single_well_reference(severity):
    model, gate3 = single_well_network()
    reference = physics.solve(gate3, np.array([severity]))
    solved = solve_network(model, NetworkState((("GS-A", severity),) if severity else ()))
    assert solved.edge_flow_sm3_per_s["INFLOW:A-03"] == pytest.approx(
        reference.gas_flow_sm3_per_s[0], rel=1e-8
    )
    assert solved.pressure_pa_abs["WH:A-03"] == pytest.approx(
        reference.wellhead_pressure_pa_abs[0], abs=0.01
    )


# Edge cases


def statuses(solution, status):
    return {w for w, s in solution.well_status.items() if s is status}


def test_zero_flow_when_every_well_is_shut_in():
    solution = solve_network(MODEL, NetworkState(shut_in_wells=frozenset(WELLS)))
    assert solution.total_flow == 0
    assert solution.regime is StationRegime.NO_FLOW
    assert all(q == 0 for q in solution.edge_flow_sm3_per_s.values())
    for well, spec in MODEL.wells.items():
        assert solution.pressure_pa_abs[f"WH:{well}"] == spec.shut_in_pa_abs
    assert solution.pressure_pa_abs["HDR-A"] == solution.pressure_pa_abs["COMP-SUCTION"] == 1.6e6


def test_closed_valve_isolates_its_pad_and_it_equalizes():
    solution = solve_network(MODEL, NetworkState(closed_valves=frozenset({"IV-B"})))
    pad_b = {w.id for w in CONFIG.wells if w.pad == "PAD-B"}
    assert statuses(solution, WellStatus.ISOLATED) == pad_b
    assert solution.edge_flow_sm3_per_s["GS-B"] == 0
    highest = max(MODEL.wells[w].shut_in_pa_abs for w in pad_b)
    assert solution.pressure_pa_abs["HDR-B"] == highest
    assert solution.total_flow > 0


def test_closed_station_valve_equalizes_the_whole_upstream_section():
    solution = solve_network(MODEL, NetworkState(closed_valves=frozenset({"IV-STATION"})))
    highest = max(s.shut_in_pa_abs for s in MODEL.wells.values())
    assert solution.total_flow == 0
    for node in ("HDR-A", "HDR-B", "MANIFOLD"):
        assert solution.pressure_pa_abs[node] == highest
    assert solution.pressure_pa_abs["COMP-SUCTION"] == 1.6e6


def test_stopped_station_shuts_in_the_field():
    solution = solve_network(
        MODEL, NetworkState(compressor_fraction=tuple((u, 0.0) for u in UNITS))
    )
    assert solution.regime is StationRegime.STOPPED
    assert solution.total_flow == 0
    assert solution.pressure_pa_abs["COMP-SUCTION"] == max(
        s.shut_in_pa_abs for s in MODEL.wells.values()
    )


def test_branch_with_no_live_source_reads_downstream_pressure():
    pad_b = frozenset(w.id for w in CONFIG.wells if w.pad == "PAD-B")
    solution = solve_network(MODEL, NetworkState(shut_in_wells=pad_b))
    assert solution.pressure_pa_abs["HDR-B"] == solution.pressure_pa_abs["MANIFOLD"]
    assert solution.edge_flow_sm3_per_s["GS-B"] == 0


def test_closed_section_with_no_source_is_undetermined_not_invented():
    pad_b = frozenset(w.id for w in CONFIG.wells if w.pad == "PAD-B")
    solution = solve_network(
        MODEL, NetworkState(closed_valves=frozenset({"IV-B"}), shut_in_wells=pad_b)
    )
    assert math.isnan(solution.pressure_pa_abs["HDR-B"])
    assert solution.total_flow > 0


def test_weak_well_backs_out_instead_of_flowing_backward():
    """A severe restriction lifts the header above the weakest well's shut-in pressure."""
    data = yaml.safe_load(NETWORK_PATH.read_text())
    weak = next(w for w in data["wells"] if w["id"] == "A-05")
    weak["shut_in_pa_abs"] = 2.0e6
    config = NetworkConfig.model_validate(data)
    model = NetworkModel(config, build_graph(config))
    solution = solve_network(model, NetworkState((("GS-A", 0.65),)))
    assert solution.well_status["A-05"] is WellStatus.BACKED_OUT
    assert solution.edge_flow_sm3_per_s["INFLOW:A-05"] == 0
    assert solution.pressure_pa_abs["WH:A-05"] == solution.pressure_pa_abs["HDR-A"]
    assert min(solution.edge_flow_sm3_per_s.values()) >= 0


def test_setpoint_above_every_shut_in_pressure_gives_no_flow():
    data = yaml.safe_load(NETWORK_PATH.read_text())
    data["compression"]["suction_setpoint_pa_abs"] = 3.6e6
    config = NetworkConfig.model_validate(data)
    solution = solve_network(NetworkModel(config, build_graph(config)), NetworkState())
    assert solution.total_flow == 0
    assert solution.regime is StationRegime.NO_FLOW
    assert set(solution.well_status.values()) == {WellStatus.BACKED_OUT}


@pytest.mark.parametrize(
    "state",
    [
        NetworkState((("GS-A", 0.71),)),
        NetworkState((("GS-A", -0.1),)),
        NetworkState((("FL-A-01", 0.71),)),
        NetworkState((("INFLOW:A-01", 0.1),)),
        NetworkState((("C-01", 0.1),)),
        NetworkState((("NOT-A-PIPE", 0.1),)),
        NetworkState(closed_valves=frozenset({"IV-Z"})),
        NetworkState(shut_in_wells=frozenset({"Z-01"})),
        NetworkState(compressor_fraction=(("C-99", 0.5),)),
        NetworkState(compressor_fraction=(("C-01", 1.5),)),
        NetworkState(compressor_fraction=(("C-01", -0.5),)),
    ],
)
def test_infeasible_or_unknown_states_are_refused(state):
    with pytest.raises(InfeasibleNetworkState):
        solve_network(MODEL, state)


def test_a_flowline_restriction_acts_on_its_own_well(  # D1, ADR 0020
):
    base = solve_network(MODEL, NetworkState())
    restricted = solve_network(MODEL, NetworkState((("FL-A-03", 0.6),)))
    lost = {w: base.edge_flow_sm3_per_s[f"INFLOW:{w}"] - restricted.edge_flow_sm3_per_s[f"INFLOW:{w}"]
            for w in MODEL.wells}  # fmt: skip
    assert lost["A-03"] > 0
    assert lost["A-03"] == max(lost.values())
    assert restricted.pressure_pa_abs["WH:A-03"] > base.pressure_pa_abs["WH:A-03"]
    assert restricted.total_flow < base.total_flow
    # Pad B shares only the trunk with Pad A, so its wells barely move.
    assert max(abs(lost[w]) for w in MODEL.wells if w.startswith("B")) < 0.05 * lost["A-03"]


def test_flowline_and_segment_restrictions_use_the_same_law():
    flowline = MODEL.graph.edges["FL-A-03"]
    segment = MODEL.graph.edges["GS-A"]
    for edge in (flowline, segment):
        k0 = MODEL.segment_resistance(edge, 0.0)
        k = MODEL.segment_resistance(edge, 0.5)
        restricted = MODEL.config.pipes.restricted_length_m
        expected = ((edge.length_m - restricted) + restricted / 0.5**5) / edge.length_m
        assert k / k0 == pytest.approx(expected)


def test_discharge_at_or_below_setpoint_is_infeasible():
    data = yaml.safe_load(NETWORK_PATH.read_text())
    data["compression"]["discharge_pa_abs"] = 1.0e6
    config = NetworkConfig.model_validate(data)
    with pytest.raises(InfeasibleNetworkState, match="discharge"):
        solve_network(NetworkModel(config, build_graph(config)), NetworkState())


def test_suction_reaching_discharge_is_infeasible():
    """Very little capacity pushes suction up, which must not silently exceed discharge."""
    data = yaml.safe_load(NETWORK_PATH.read_text())
    data["compression"]["discharge_pa_abs"] = 1.8e6
    config = NetworkConfig.model_validate(data)
    model = NetworkModel(config, build_graph(config))
    with pytest.raises(InfeasibleNetworkState, match="reached discharge"):
        solve_network(
            model, NetworkState(compressor_fraction=tuple((u, 0.1) for u in model.capacity))
        )


def test_unconverged_solve_raises_instead_of_returning_a_result():
    data = yaml.safe_load(NETWORK_PATH.read_text())
    data["solver"]["max_iterations"] = 1
    config = NetworkConfig.model_validate(data)
    with pytest.raises(SolverDidNotConverge):
        solve_network(NetworkModel(config, build_graph(config)), NetworkState())
