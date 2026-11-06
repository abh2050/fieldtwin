"""Add generated field pages to the editable draw.io file, so diagrams can't drift from the config."""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import quoteattr

import yaml

from packages.scenario_engine.network_graph import EdgeType, NodeType, build_graph, load_network

REPO = Path(__file__).resolve().parents[1]
DRAWIO = REPO / "docs" / "architecture.drawio"
SYN = "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;"
BOX = "rounded=1;whiteSpace=wrap;html=1;"
SITE = "rounded=1;whiteSpace=wrap;html=1;dashed=1;"
GROUP = "rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fillColor=none;strokeColor=#999999;"
NOTE = "text;html=1;align=left;fontStyle=2;"
LIFE = "endArrow=none;html=1;dashed=1;strokeColor=#888888;"


class Page:
    def __init__(self, page_id: str, name: str, width: int, height: int):
        self.page_id, self.name, self.width, self.height = page_id, name, width, height
        self.cells: list[str] = []
        self.count = 0

    def box(
        self,
        cell: str,
        label: str,
        x: float,
        y: float,
        w: float = 110,
        h: float = 44,
        style: str = SYN,
    ) -> str:
        self.cells.append(
            f'<mxCell id={quoteattr(cell)} value={quoteattr(label)} style={quoteattr(style)} vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        return cell

    def edge(
        self,
        source: str,
        target: str,
        label: str = "",
        style: str = "endArrow=block;html=1;fontSize=10;labelBackgroundColor=#ffffff;",
        points: tuple[tuple[float, float], ...] = (),
    ) -> None:
        self.count += 1
        waypoints = ""
        if points:
            inner = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points)
            waypoints = f'<Array as="points">{inner}</Array>'
        self.cells.append(
            f'<mxCell id="e{self.count}" value={quoteattr(label)} style={quoteattr(style)} edge="1" source={quoteattr(source)} target={quoteattr(target)} parent="1">'
            f'<mxGeometry relative="1" as="geometry">{waypoints}</mxGeometry></mxCell>'
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        label: str = "",
        style: str = "endArrow=block;html=1;fontSize=11;labelBackgroundColor=#ffffff;",
    ) -> None:
        self.count += 1
        self.cells.append(
            f'<mxCell id="l{self.count}" value={quoteattr(label)} style={quoteattr(style)} edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x1}" y="{y1}" as="sourcePoint"/><mxPoint x="{x2}" y="{y2}" as="targetPoint"/></mxGeometry></mxCell>'
        )

    def xml(self) -> str:
        body = "\n        ".join(self.cells)
        return (
            f'  <diagram id="{self.page_id}" name={quoteattr(self.name)}>\n'
            f'    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" page="1" pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0">\n'
            '      <root>\n        <mxCell id="0"/>\n        <mxCell id="1" parent="0"/>\n'
            f"        {body}\n      </root>\n    </mxGraphModel>\n  </diagram>\n"
        )


def _group(
    page: Page, cell: str, label: str, items: list[str], x: float, y: float, columns: int = 1
) -> None:
    """A labeled container, because connector lines across this many assets would be unreadable."""
    rows = (len(items) + columns - 1) // columns
    width = columns * 120 + 20
    page.box(cell, label, x, y, width, 40 + rows * 50 + 10, GROUP)
    for i, item in enumerate(items):
        page.box(item, item, x + 10 + (i % columns) * 120, y + 40 + (i // columns) * 50, 110, 40)


def topology_page() -> Page:
    facility = yaml.safe_load((REPO / "config/facility/aether_field.yaml").read_text())["assets"]
    page = Page("aether-topology", "AETHER asset topology (Gate 4)", 1500, 560)
    page.box(
        "note",
        "Asset hierarchy of the fictional AETHER Field. All assets are SYNTHETIC. Generated from config/facility/aether_field.yaml. Physical connections are on the next page.",
        20,
        10,
        1400,
        26,
        NOTE,
    )
    page.box("root", "AETHER Field (fictional)", 620, 50, 220, 40)
    y = 130
    pads = facility["well_pads"]
    _group(page, pads[0]["asset_id"], "PAD-A: Well Pad A", pads[0]["wells"], 20, y)
    _group(page, pads[1]["asset_id"], "PAD-B: Well Pad B", pads[1]["wells"], 170, y)
    gathering = facility["gathering_network"]
    equipment = (
        gathering["gathering_segments"]
        + gathering["isolation_valves"]
        + gathering["headers"]
        + gathering["manifolds"]
    )
    _group(
        page,
        gathering["asset_id"],
        "GATHERING: Gathering Network",
        equipment + gathering["flowlines"],
        320,
        y,
        4,
    )
    station = facility["compression_station"]
    _group(
        page,
        station["asset_id"],
        "COMP-STATION: Compression Station",
        station["compressors"] + station["interfaces"],
        830,
        y,
    )
    operations = facility["field_operations"]
    _group(
        page,
        operations["asset_id"],
        "FIELD-OPS: Field Operations",
        operations["maintenance_locations"] + operations["inspection_locations"],
        1010,
        y,
    )
    for child in (
        pads[0]["asset_id"],
        pads[1]["asset_id"],
        gathering["asset_id"],
        station["asset_id"],
        operations["asset_id"],
    ):
        # Anchored to the group tops, so an arrow can't cross a neighboring group.
        page.edge(
            "root", child, style="endArrow=block;html=1;exitX=0.5;exitY=1;entryX=0.5;entryY=0;"
        )
    return page


def network_page() -> Page:
    config = load_network()
    graph = build_graph(config)
    page = Page("aether-network", "AETHER physical network (Gate 4)", 1500, 860)
    page.box(
        "note",
        "Typed directed graph. Schematic, not to scale. Boxes hold a pressure and arrows carry gas, except compressor boxes, which are edges in the graph. Generated from config/facility/aether_network.yaml. Fictional.",
        20,
        10,
        1400,
        26,
        NOTE,
    )
    pads = {"PAD-A": (40, 340), "PAD-B": (1330, 1000)}
    for pad, (well_x, header_x) in pads.items():
        wells = [w for w in config.wells if w.pad == pad]
        header = next(j.id for j in config.junctions if j.pad == pad)
        page.box(header, f"{header} (junction)", header_x - 0, 380, 120, 50)
        for i, well in enumerate(wells):
            y = 170 + i * 88
            page.box(
                f"WH:{well.id}",
                f"{well.id} wellhead\nshut-in {well.shut_in_pa_abs / 1e6:.2f} MPa",
                well_x,
                y,
                130,
                50,
            )
            start, end = (f"WH:{well.id}", header)
            page.edge(start, end, f"{well.flowline} {well.flowline_m:.0f} m")
    page.box("MANIFOLD", "MANIFOLD (shared)", 670, 380, 160, 50)
    page.box(
        "COMP-SUCTION",
        f"COMP-SUCTION\nsetpoint {config.compression.suction_setpoint_pa_abs / 1e6:.1f} MPa",
        670,
        210,
        160,
        56,
    )
    page.box(
        "COMP-DISCHARGE",
        f"COMP-DISCHARGE (boundary)\n{config.compression.discharge_pa_abs / 1e6:.1f} MPa",
        670,
        60,
        160,
        50,
    )
    for segment in config.segments:
        page.edge(
            segment.source,
            segment.target,
            f"{segment.id} {segment.length_m:.0f} m, {segment.diameter_m * 1000:.0f} mm\nvalve {segment.isolation_valve}",
        )
    for i, unit in enumerate(config.compression.units):
        x = [440, 560, 860, 980][i]
        page.box(unit.id, f"{unit.id}\n{unit.capacity_sm3_per_s} sm3/s", x, 135, 80, 46)
        page.edge("COMP-SUCTION", unit.id)
        page.edge(unit.id, "COMP-DISCHARGE")
    page.box("MAINT-BASE", "MAINT-BASE (site)", 670, 600, 160, 44, SITE)
    page.box("INSPECT-A", "INSPECT-A (site)", 340, 600, 120, 44, SITE)
    page.box("INSPECT-B", "INSPECT-B (site)", 1000, 600, 120, 44, SITE)
    access = "dashed=1;endArrow=open;html=1;strokeColor=#888888;fontSize=10;"
    for edge in graph.edges.values():
        if edge.edge_type is not EdgeType.ACCESS_ROUTE:
            continue
        if edge.target == "COMP-SUCTION":
            # Route around the manifold, so this can't be read as a flow path through it.
            style = access + "exitX=1;exitY=0.25;entryX=1;entryY=0.5;"
            page.edge(edge.source, edge.target, "", style, ((848, 611), (848, 238)))
        else:
            page.edge(edge.source, edge.target, "", access)
    types = sorted(t.value for t in NodeType)
    page.box(
        "types",
        "Node types: "
        + ", ".join(types)
        + ". Each well also has a reservoir boundary behind its wellhead (WELL_INFLOW). Dashed arrows are access routes, not flow.",
        20,
        700,
        1400,
        44,
        NOTE,
    )
    return page


def sequence_page() -> Page:
    page = Page("simulation-sequence", "Field simulation sequence (Gate 4)", 1500, 760)
    page.box(
        "note",
        "One scenario run. Truth comes from one coupled solve per distinct state, and telemetry is applied afterward, so sensor faults can't change the physics.",
        20,
        10,
        1400,
        26,
        NOTE,
    )
    actors = [
        "Scenario catalog",
        "Field simulator",
        "Network solver",
        "Telemetry layer",
        "Invariant checks",
        "Pipeline",
        "PostgreSQL",
    ]
    xs = {name: 80 + i * 210 for i, name in enumerate(actors)}
    for name, x in xs.items():
        page.box(f"a:{name}", name, x - 80, 50, 160, 40, BOX)
        page.line(x, 90, x, 720, style=LIFE)
    steps = [
        ("Pipeline", "Field simulator", "1. run this scenario"),
        ("Scenario catalog", "Field simulator", "2. scenario, seed, parameter set"),
        ("Field simulator", "Network solver", "3. NetworkState at each sample"),
        ("Network solver", "Field simulator", "4. flows, pressures, regime, diagnostics"),
        ("Field simulator", "Telemetry layer", "5. truth table"),
        ("Telemetry layer", "Field simulator", "6. readings, noise, faults, quality"),
        ("Field simulator", "Invariant checks", "7. truth and telemetry"),
        ("Invariant checks", "Pipeline", "8. pass, or the run is refused"),
        ("Pipeline", "PostgreSQL", "9. run, series, links, events"),
        ("PostgreSQL", "Pipeline", "10. constraints accept or refuse"),
    ]
    for i, (source, target, label) in enumerate(steps):
        y = 130 + i * 58
        page.line(xs[source], y, xs[target], y, label)
    return page


def main() -> int:
    text = DRAWIO.read_text()
    pages = [topology_page(), network_page(), sequence_page()]
    for page in pages:
        text = re.sub(rf'  <diagram id="{page.page_id}".*?</diagram>\n', "", text, flags=re.S)
    text = text.replace("</mxfile>", "".join(p.xml() for p in pages) + "</mxfile>")
    DRAWIO.write_text(text)
    print(f"pages: {re.findall(r'<diagram id=.([a-z-]+)', text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
