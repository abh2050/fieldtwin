"""A typed, directed physical network, separate from evidence and identity relationships.

Pressure lives at nodes. Equipment that moves gas lives on edges. A closed valve or stopped machine
is a state of an edge, so the graph itself stays fixed.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .config import Ambient, Gas, StandardConditions

REPO_ROOT = Path(__file__).resolve().parents[2]
NETWORK_PATH = REPO_ROOT / "config" / "facility" / "aether_network.yaml"
SOURCE_PREFIX = "RES:"
WELLHEAD_PREFIX = "WH:"


class NetworkGraphError(ValueError):
    """The declared connectivity isn't physically consistent."""


class NodeType(StrEnum):
    RESERVOIR_BOUNDARY = "RESERVOIR_BOUNDARY"
    WELLHEAD = "WELLHEAD"
    JUNCTION = "JUNCTION"
    MANIFOLD = "MANIFOLD"
    SUCTION_HEADER = "SUCTION_HEADER"
    DISCHARGE_BOUNDARY = "DISCHARGE_BOUNDARY"
    SITE = "SITE"


class EdgeType(StrEnum):
    WELL_INFLOW = "WELL_INFLOW"
    FLOWLINE = "FLOWLINE"
    GATHERING_SEGMENT = "GATHERING_SEGMENT"
    COMPRESSION = "COMPRESSION"
    ACCESS_ROUTE = "ACCESS_ROUTE"


FLOW_EDGES = {
    EdgeType.WELL_INFLOW,
    EdgeType.FLOWLINE,
    EdgeType.GATHERING_SEGMENT,
    EdgeType.COMPRESSION,
}
ALLOWED_CONNECTIONS = {
    (EdgeType.WELL_INFLOW, NodeType.RESERVOIR_BOUNDARY, NodeType.WELLHEAD),
    (EdgeType.FLOWLINE, NodeType.WELLHEAD, NodeType.JUNCTION),
    (EdgeType.GATHERING_SEGMENT, NodeType.JUNCTION, NodeType.MANIFOLD),
    (EdgeType.GATHERING_SEGMENT, NodeType.MANIFOLD, NodeType.SUCTION_HEADER),
    (EdgeType.COMPRESSION, NodeType.SUCTION_HEADER, NodeType.DISCHARGE_BOUNDARY),
    (EdgeType.ACCESS_ROUTE, NodeType.SITE, NodeType.SITE),
    (EdgeType.ACCESS_ROUTE, NodeType.SITE, NodeType.JUNCTION),
    (EdgeType.ACCESS_ROUTE, NodeType.SITE, NodeType.SUCTION_HEADER),
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NetworkInfo(Strict):
    name: str
    version: int = Field(gt=0)
    provenance_class: str = Field(pattern="^SYNTHETIC$")
    coordinate_system: str


class Pipes(Strict):
    darcy_friction_factor: float = Field(gt=0)
    restricted_length_m: float = Field(gt=0)


class WellDefaults(Strict):
    deliverability_exponent: float = Field(ge=0.5, le=1.0)
    flowline_diameter_m: float = Field(gt=0)


class WellSpec(Strict):
    id: str
    pad: str
    flowline: str
    shut_in_pa_abs: float = Field(gt=0)
    coefficient: float = Field(gt=0)
    flowline_m: float = Field(gt=0)
    x: float
    y: float


class JunctionSpec(Strict):
    id: str
    node_type: NodeType
    pad: str | None = None
    x: float
    y: float


class SegmentSpec(Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    length_m: float = Field(gt=0)
    diameter_m: float = Field(gt=0)
    isolation_valve: str


class CompressorSpec(Strict):
    id: str
    capacity_sm3_per_s: float = Field(gt=0)


class Compression(Strict):
    suction_setpoint_pa_abs: float = Field(gt=0)
    discharge_pa_abs: float = Field(gt=0)
    reference_suction_pa_abs: float = Field(gt=0)
    max_compression_ratio: float = Field(gt=1)
    units: list[CompressorSpec] = Field(min_length=1)


class SiteSpec(Strict):
    id: str
    node_type: NodeType
    x: float
    y: float
    serves: list[str]


class ValidityEnvelope(Strict):
    max_mach_number: float = Field(gt=0, le=1)
    min_reynolds_number_when_flowing: float = Field(gt=0)
    max_pressure_pa_abs: float = Field(gt=0)
    min_pressure_pa_abs: float = Field(gt=0)
    severity_limit: float = Field(gt=0, lt=1)


class SolverSettings(Strict):
    max_iterations: int = Field(gt=0)
    max_active_set_passes: int = Field(gt=0)
    relative_residual_tolerance: float = Field(gt=0)


class NetworkConfig(Strict):
    network: NetworkInfo
    gas: Gas
    standard_conditions: StandardConditions
    ambient: Ambient
    pipes: Pipes
    well_defaults: WellDefaults
    wells: list[WellSpec]
    junctions: list[JunctionSpec]
    segments: list[SegmentSpec]
    compression: Compression
    sites: list[SiteSpec]
    validity_envelope: ValidityEnvelope
    solver: SolverSettings


@dataclass(frozen=True)
class Node:
    node_id: str
    node_type: NodeType
    asset_id: str
    x: float | None
    y: float | None


@dataclass(frozen=True)
class Edge:
    edge_id: str
    edge_type: EdgeType
    source: str
    target: str
    element_asset_id: str
    length_m: float | None = None
    diameter_m: float | None = None
    valve_asset_id: str | None = None


@dataclass(frozen=True)
class NetworkGraph:
    nodes: dict[str, Node]
    edges: dict[str, Edge]

    def flow_edges(self) -> list[Edge]:
        return [e for e in self.edges.values() if e.edge_type in FLOW_EDGES]

    def downstream_edge(self, node_id: str) -> Edge | None:
        """The single flow edge leaving a node, for every node below the suction header."""
        leaving = [
            e
            for e in self.flow_edges()
            if e.source == node_id and e.edge_type is not EdgeType.COMPRESSION
        ]
        return leaving[0] if leaving else None

    def upstream_of(self, node_id: str) -> set[str]:
        """Every node whose gas passes through this node."""
        found: set[str] = set()
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for edge in self.flow_edges():
                if edge.target == current and edge.source not in found:
                    found.add(edge.source)
                    frontier.append(edge.source)
        return found

    def well_ids(self) -> list[str]:
        return [n.asset_id for n in self.nodes.values() if n.node_type is NodeType.WELLHEAD]


def build_graph(config: NetworkConfig) -> NetworkGraph:
    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}

    def add_node(node: Node) -> None:
        if node.node_id in nodes:
            raise NetworkGraphError(f"duplicate node {node.node_id}")
        nodes[node.node_id] = node

    def add_edge(edge: Edge) -> None:
        if edge.edge_id in edges:
            raise NetworkGraphError(f"duplicate edge {edge.edge_id}")
        edges[edge.edge_id] = edge

    for junction in config.junctions:
        add_node(Node(junction.id, junction.node_type, junction.id, junction.x, junction.y))
    for site in config.sites:
        add_node(Node(site.id, site.node_type, site.id, site.x, site.y))
    header_of = {j.pad: j.id for j in config.junctions if j.pad}
    for well in config.wells:
        if well.pad not in header_of:
            raise NetworkGraphError(f"{well.id} names unknown pad {well.pad}")
        wellhead = f"{WELLHEAD_PREFIX}{well.id}"
        boundary = f"{SOURCE_PREFIX}{well.id}"
        add_node(Node(wellhead, NodeType.WELLHEAD, well.id, well.x, well.y))
        add_node(Node(boundary, NodeType.RESERVOIR_BOUNDARY, well.id, None, None))
        add_edge(Edge(f"INFLOW:{well.id}", EdgeType.WELL_INFLOW, boundary, wellhead, well.id))
        add_edge(
            Edge(
                well.flowline,
                EdgeType.FLOWLINE,
                wellhead,
                header_of[well.pad],
                well.flowline,
                well.flowline_m,
                config.well_defaults.flowline_diameter_m,
            )
        )
    for segment in config.segments:
        add_edge(
            Edge(
                segment.id,
                EdgeType.GATHERING_SEGMENT,
                segment.source,
                segment.target,
                segment.id,
                segment.length_m,
                segment.diameter_m,
                segment.isolation_valve,
            )
        )
    suction = next(j.id for j in config.junctions if j.node_type is NodeType.SUCTION_HEADER)
    discharge = next(j.id for j in config.junctions if j.node_type is NodeType.DISCHARGE_BOUNDARY)
    for unit in config.compression.units:
        add_edge(Edge(unit.id, EdgeType.COMPRESSION, suction, discharge, unit.id))
    for site in config.sites:
        for served in site.serves:
            add_edge(
                Edge(f"ACCESS:{site.id}:{served}", EdgeType.ACCESS_ROUTE, site.id, served, site.id)
            )
    graph = NetworkGraph(nodes, edges)
    validate_graph(graph)
    return graph


def validate_graph(graph: NetworkGraph) -> None:
    """Refuse connectivity that isn't physically consistent."""
    for edge in graph.edges.values():
        if edge.source not in graph.nodes or edge.target not in graph.nodes:
            raise NetworkGraphError(f"{edge.edge_id} connects an unknown node")
        if edge.source == edge.target:
            raise NetworkGraphError(f"{edge.edge_id} connects a node to itself")
        connection = (
            edge.edge_type,
            graph.nodes[edge.source].node_type,
            graph.nodes[edge.target].node_type,
        )
        if connection not in ALLOWED_CONNECTIONS:
            raise NetworkGraphError(
                f"{edge.edge_id}: {connection[0]} can't connect {connection[1]} to {connection[2]}"
            )
    _check_acyclic(graph)
    for node in graph.nodes.values():
        if node.node_type is NodeType.SITE:
            continue
        leaving = [e for e in graph.flow_edges() if e.source == node.node_id]
        kinds = {e.edge_type for e in leaving}
        if node.node_type is NodeType.DISCHARGE_BOUNDARY:
            if leaving:
                raise NetworkGraphError(f"{node.node_id} is a boundary and can't have outflow")
        elif node.node_type is NodeType.SUCTION_HEADER:
            if kinds != {EdgeType.COMPRESSION}:
                raise NetworkGraphError(f"{node.node_id} must discharge through compressors")
        elif len(leaving) != 1:
            raise NetworkGraphError(f"{node.node_id} needs exactly one outflow path")
        if node.node_type is NodeType.RESERVOIR_BOUNDARY:
            continue
        if not [e for e in graph.flow_edges() if e.target == node.node_id]:
            raise NetworkGraphError(f"{node.node_id} has no inflow, so it can't carry gas")
    _check_reaches_discharge(graph)
    _check_lengths(graph)


def _check_acyclic(graph: NetworkGraph) -> None:
    pending = {n: 0 for n in graph.nodes}
    flow = graph.flow_edges()
    for edge in flow:
        pending[edge.target] += 1
    ready = [n for n, count in pending.items() if count == 0]
    seen = 0
    while ready:
        current = ready.pop()
        seen += 1
        for edge in flow:
            if edge.source == current:
                pending[edge.target] -= 1
                if pending[edge.target] == 0:
                    ready.append(edge.target)
    if seen != len(graph.nodes):
        raise NetworkGraphError("the flow network contains a cycle")


def _check_reaches_discharge(graph: NetworkGraph) -> None:
    discharge = [n for n in graph.nodes.values() if n.node_type is NodeType.DISCHARGE_BOUNDARY]
    if len(discharge) != 1:
        raise NetworkGraphError("the network needs exactly one discharge boundary")
    reached = graph.upstream_of(discharge[0].node_id)
    for node in graph.nodes.values():
        if node.node_type in (NodeType.SITE, NodeType.DISCHARGE_BOUNDARY):
            continue
        if node.node_id not in reached:
            raise NetworkGraphError(f"{node.node_id} has no path to the discharge boundary")


def _check_lengths(graph: NetworkGraph) -> None:
    """A pipe can't be shorter than the straight line between its ends."""
    for edge in graph.flow_edges():
        if edge.length_m is None:
            continue
        a, b = graph.nodes[edge.source], graph.nodes[edge.target]
        if a.x is None or b.x is None or a.y is None or b.y is None:
            continue
        straight = math.hypot(b.x - a.x, b.y - a.y)
        if edge.length_m < straight:
            raise NetworkGraphError(
                f"{edge.edge_id} is {edge.length_m} m long but its ends are {straight:.0f} m apart"
            )


def load_network(path: Path = NETWORK_PATH, **overrides: Any) -> NetworkConfig:
    data = yaml.safe_load(path.read_text())
    data.update(overrides)
    return NetworkConfig.model_validate(data)


def asset_ids(graph: NetworkGraph) -> Iterable[str]:
    for node in graph.nodes.values():
        yield node.asset_id
    for edge in graph.edges.values():
        yield edge.element_asset_id
        if edge.valve_asset_id:
            yield edge.valve_asset_id
