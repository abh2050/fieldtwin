"""What the decision engine knows about the fictional field, derived from the Gate 4 network.

Consequence is the share of the field's wells whose gas passes through an asset. It's computed from
the validated network graph, not typed in, so a reader can check it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

from packages.scenario_engine.network_graph import EdgeType, NetworkGraph, NodeType

BASE = "MAINT-BASE"


def _xy(node) -> tuple[float, float]:
    if node.x is None or node.y is None:
        raise ValueError(f"{node.node_id} has no location")
    return float(node.x), float(node.y)


@dataclass(frozen=True)
class AssetFacts:
    asset_id: str
    kind: str
    x: float
    y: float
    wells_through: frozenset[str]
    consequence_share: float


class FieldTopology:
    def __init__(self, graph: NetworkGraph, parallel_compressor_share: float):
        self.graph = graph
        self.compressor_share = parallel_compressor_share

    @cached_property
    def wells(self) -> list[str]:
        return sorted(self.graph.well_ids())

    def _wells_upstream_of_node(self, node_id: str) -> set[str]:
        nodes = self.graph.upstream_of(node_id) | {node_id}
        return {
            self.graph.nodes[n].asset_id
            for n in nodes
            if self.graph.nodes[n].node_type is NodeType.WELLHEAD
        }

    @cached_property
    def facts(self) -> dict[str, AssetFacts]:
        found: dict[str, AssetFacts] = {}
        total = len(self.wells)
        for node in self.graph.nodes.values():
            if (
                node.x is None
                or node.y is None
                or node.node_type
                in (
                    NodeType.SITE,
                    NodeType.DISCHARGE_BOUNDARY,
                )
            ):
                continue
            kind = "well" if node.node_type is NodeType.WELLHEAD else node.node_type.value.lower()
            wells = frozenset(self._wells_upstream_of_node(node.node_id))
            found[node.asset_id] = AssetFacts(
                node.asset_id, kind, node.x, node.y, wells, len(wells) / total
            )
        for edge in self.graph.edges.values():
            if edge.edge_type is EdgeType.FLOWLINE or edge.edge_type is EdgeType.GATHERING_SEGMENT:
                (ax, ay), (bx, by) = (
                    _xy(self.graph.nodes[edge.source]),
                    _xy(self.graph.nodes[edge.target]),
                )
                wells = frozenset(self._wells_upstream_of_node(edge.source))
                kind = "flowline" if edge.edge_type is EdgeType.FLOWLINE else "gathering_segment"
                found[edge.element_asset_id] = AssetFacts(
                    edge.element_asset_id,
                    kind,
                    (ax + bx) / 2,
                    (ay + by) / 2,
                    wells,
                    len(wells) / total,
                )
            elif edge.edge_type is EdgeType.COMPRESSION:
                sx, sy = _xy(self.graph.nodes[edge.source])
                found[edge.element_asset_id] = AssetFacts(
                    edge.element_asset_id,
                    "compressor",
                    sx,
                    sy,
                    frozenset(self.wells),
                    self.compressor_share,
                )
        return found

    def base(self) -> tuple[float, float]:
        node = self.graph.nodes[BASE]
        assert node.x is not None and node.y is not None
        return node.x, node.y

    def location(self, asset_id: str) -> tuple[float, float]:
        if asset_id == BASE:
            return self.base()
        fact = self.facts[asset_id]
        return fact.x, fact.y

    def distance_m(self, a: str, b: str) -> float:
        (x1, y1), (x2, y2) = self.location(a), self.location(b)
        return math.hypot(x2 - x1, y2 - y1)

    def assets_through(self, asset_id: str) -> set[str]:
        """Every asset whose gas passes through this one, including itself."""
        if asset_id not in self.facts:
            # A valve is located by the edge it sits on.
            edge = next(
                (e for e in self.graph.edges.values() if e.valve_asset_id == asset_id), None
            )
            if edge is None:
                return {asset_id}
            asset_id = edge.element_asset_id
        wells = self.facts[asset_id].wells_through
        return {
            other.asset_id
            for other in self.facts.values()
            if other.wells_through and other.wells_through <= wells and other.kind != "compressor"
        } | {asset_id}
