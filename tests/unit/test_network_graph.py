"""The physical network is complete, typed, and internally consistent."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from packages.scenario_engine.network_graph import (
    NETWORK_PATH,
    Edge,
    EdgeType,
    NetworkConfig,
    NetworkGraph,
    NetworkGraphError,
    Node,
    NodeType,
    asset_ids,
    build_graph,
    load_network,
    validate_graph,
)
from tests.conftest import REPO_ROOT

CONFIG = load_network()
GRAPH = build_graph(CONFIG)
FACILITY = yaml.safe_load((REPO_ROOT / "config/facility/aether_field.yaml").read_text())


def count(node_type):
    return sum(n.node_type is node_type for n in GRAPH.nodes.values())


def edges_of(edge_type):
    return [e for e in GRAPH.edges.values() if e.edge_type is edge_type]


def test_network_has_every_required_element():
    assert count(NodeType.WELLHEAD) == 12
    assert count(NodeType.RESERVOIR_BOUNDARY) == 12
    assert count(NodeType.JUNCTION) == 2  # One header per pad.
    assert count(NodeType.MANIFOLD) == 1
    assert count(NodeType.SUCTION_HEADER) == 1
    assert count(NodeType.DISCHARGE_BOUNDARY) == 1
    assert count(NodeType.SITE) == 3
    assert len(edges_of(EdgeType.WELL_INFLOW)) == 12
    assert len(edges_of(EdgeType.FLOWLINE)) == 12
    assert len(edges_of(EdgeType.GATHERING_SEGMENT)) == 3
    assert len(edges_of(EdgeType.COMPRESSION)) == 4
    assert len(edges_of(EdgeType.ACCESS_ROUTE)) == 5


def test_network_is_declared_synthetic():
    assert CONFIG.network.provenance_class == "SYNTHETIC"
    assert "fictional" in CONFIG.network.coordinate_system


def facility_assets():
    assets = FACILITY["assets"]
    found = {p["asset_id"] for p in assets["well_pads"]}
    found |= {w for p in assets["well_pads"] for w in p["wells"]}
    for section in ("gathering_network", "compression_station", "field_operations"):
        for value in assets[section].values():
            if isinstance(value, list):
                found |= set(value)
            else:
                found.add(value)
    return found


def test_every_graph_asset_is_a_declared_fictional_asset():
    assert set(asset_ids(GRAPH)) <= facility_assets()


def test_pad_wells_match_the_facility_definition():
    declared = {p["asset_id"]: set(p["wells"]) for p in FACILITY["assets"]["well_pads"]}
    for pad, wells in declared.items():
        header = next(j.id for j in CONFIG.junctions if j.pad == pad)
        assert {w.id for w in CONFIG.wells if GRAPH.edges[w.flowline].target == header} == wells


def test_every_well_reaches_one_manifold_through_its_pad():
    for well in CONFIG.wells:
        path = []
        node = f"WH:{well.id}"
        while node != "COMP-SUCTION":
            edge = GRAPH.downstream_edge(node)
            path.append(edge.edge_id)
            node = edge.target
        assert path[-1] == "GS-TRUNK"
        assert path[-2] == ("GS-A" if well.pad == "PAD-A" else "GS-B")


def test_declared_feeds_are_physically_connected():
    """Facility-level FEEDS statements must agree with the pressure network."""
    node_of = {e.element_asset_id: e.target for e in edges_of(EdgeType.GATHERING_SEGMENT)}
    for connection in FACILITY["flow_connections"]:
        source, target = connection["source"], connection["target"]
        if target == "COMP-STATION":
            assert node_of[source] == "COMP-SUCTION"
            continue
        start = f"WH:{source}" if source in GRAPH.well_ids() else node_of[source]
        assert start in GRAPH.upstream_of(node_of[target]), connection


def test_maintenance_sites_are_not_in_the_flow_network():
    flow_nodes = {e.source for e in GRAPH.flow_edges()} | {e.target for e in GRAPH.flow_edges()}
    assert (
        not {n.node_id for n in GRAPH.nodes.values() if n.node_type is NodeType.SITE} & flow_nodes
    )


def with_edge(*extra):
    return NetworkGraph(dict(GRAPH.nodes), {**GRAPH.edges, **{e.edge_id: e for e in extra}})


@pytest.mark.parametrize(
    ("edge", "message"),
    [
        (
            Edge("BAD", EdgeType.GATHERING_SEGMENT, "MANIFOLD", "HDR-A", "GS-A", 9000, 0.1),
            "can't connect",
        ),
        (Edge("BAD", EdgeType.COMPRESSION, "COMP-SUCTION", "WH:A-01", "C-01"), "can't connect"),
        (Edge("BAD", EdgeType.WELL_INFLOW, "WH:A-01", "HDR-A", "A-01"), "can't connect"),
        (
            Edge("BAD", EdgeType.FLOWLINE, "WH:A-01", "HDR-A", "FL-A-01", 900, 0.08),
            "exactly one outflow",
        ),
        (Edge("BAD", EdgeType.FLOWLINE, "WH:A-01", "WH:A-01", "FL-A-01", 900, 0.08), "itself"),
        (
            Edge("BAD", EdgeType.FLOWLINE, "WH:A-01", "NOWHERE", "FL-A-01", 900, 0.08),
            "unknown node",
        ),
        (
            Edge("BAD", EdgeType.COMPRESSION, "COMP-DISCHARGE", "COMP-SUCTION", "C-01"),
            "can't connect",
        ),
    ],
)
def test_inconsistent_connectivity_is_refused(edge, message):
    with pytest.raises(NetworkGraphError, match=message):
        validate_graph(with_edge(edge))


def test_a_cycle_is_refused_even_when_each_connection_type_is_allowed():
    nodes = dict(GRAPH.nodes)
    nodes["M2"] = Node("M2", NodeType.MANIFOLD, "MANIFOLD", 0.0, 0.0)
    edges = dict(GRAPH.edges)
    edges["GS-TRUNK"] = Edge(
        "GS-TRUNK", EdgeType.GATHERING_SEGMENT, "MANIFOLD", "COMP-SUCTION", "GS-TRUNK", 1500, 0.2
    )
    edges["LOOP"] = Edge("LOOP", EdgeType.COMPRESSION, "COMP-SUCTION", "COMP-SUCTION", "C-01")
    with pytest.raises(NetworkGraphError):
        validate_graph(NetworkGraph(nodes, edges))


def test_a_node_with_no_outflow_is_refused():
    edges = {k: v for k, v in GRAPH.edges.items() if k != "GS-TRUNK"}
    with pytest.raises(NetworkGraphError):
        validate_graph(NetworkGraph(dict(GRAPH.nodes), edges))


def test_a_junction_with_no_inflow_is_refused():
    edges = {k: v for k, v in GRAPH.edges.items() if GRAPH.edges[k].target != "HDR-B"}
    with pytest.raises(NetworkGraphError):
        validate_graph(NetworkGraph(dict(GRAPH.nodes), edges))


def raw():
    return yaml.safe_load(NETWORK_PATH.read_text())


def test_pipe_shorter_than_the_distance_between_its_ends_is_refused():
    data = raw()
    data["segments"][0]["length_m"] = 100
    with pytest.raises(NetworkGraphError, match="ends are"):
        build_graph(NetworkConfig.model_validate(data))


def test_well_on_an_unknown_pad_is_refused():
    data = raw()
    data["wells"][0]["pad"] = "PAD-Z"
    with pytest.raises(NetworkGraphError, match="unknown pad"):
        build_graph(NetworkConfig.model_validate(data))


def test_duplicate_well_is_refused():
    data = raw()
    data["wells"].append(dict(data["wells"][0]))
    with pytest.raises(NetworkGraphError, match="duplicate"):
        build_graph(NetworkConfig.model_validate(data))


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("network", "provenance_class", "OBSERVED"),
        ("gas", "temperature_k", -1),
        ("well_defaults", "deliverability_exponent", 1.5),
        ("compression", "max_compression_ratio", 0.5),
        ("network", "unexpected", 1),
    ],
)
def test_invalid_network_configuration_is_refused(section, field, value):
    data = raw()
    data[section][field] = value
    with pytest.raises(ValidationError):
        NetworkConfig.model_validate(data)
