import { useQuery } from "@tanstack/react-query";
import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { webglAvailable } from "@/components/ErrorBoundary";
import { Page } from "@/components/Page";
import { QueryState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { request, type Paged } from "@/lib/api";
import type { NetworkEdge, NetworkNode, Recommendation } from "@/lib/types";

type Network = { coordinate_system: string; note: string; nodes: NetworkNode[]; edges: NetworkEdge[] };

// AETHER Field has no real location. Local metres are drawn on a blank canvas near 0°, 0° purely so
// MapLibre can pan and zoom them; no basemap is loaded and no coordinate is geographic.
const toLngLat = (x: number, y: number): [number, number] => [x / 111_320, y / 110_574];

const NODE_COLORS: Record<string, string> = {
  WELLHEAD: "#2f7d4f",
  RESERVOIR_BOUNDARY: "#94a3b8",
  SITE: "#0f766e",
  MANIFOLD: "#3b6ea5",
  JUNCTION: "#6b7280",
  SUCTION_HEADER: "#b45309",
  DISCHARGE_BOUNDARY: "#7c3aed",
};
const color = (t: string) => NODE_COLORS[t] ?? "#475569";

// Drawn when WebGL is unavailable: the same nodes and edges as plain SVG.
function Schematic({ net, highlighted, onSelect }: { net: Network; highlighted: Set<string>; onSelect: (n: NetworkNode) => void }) {
  const xs = net.nodes.map((n) => n.local_x_m);
  const ys = net.nodes.map((n) => n.local_y_m);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = Math.max(x1 - x0, y1 - y0) * 0.05 || 10;
  const byId = new Map(net.nodes.map((n) => [n.node_id, n]));
  return (
    <svg
      viewBox={`${x0 - pad} ${-(y1 + pad)} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`}
      className="h-[560px] w-full rounded-lg border bg-muted/40"
      role="img"
      aria-label="Schematic of the fictional AETHER Field gathering network"
      preserveAspectRatio="xMidYMid meet"
    >
      {net.edges.map((e) => {
        const a = byId.get(e.from_node_id);
        const b = byId.get(e.to_node_id);
        if (!a || !b) return null;
        const flagged = !!e.element_asset_id && highlighted.has(e.element_asset_id);
        return (
          <line key={e.edge_id} x1={a.local_x_m} y1={-a.local_y_m} x2={b.local_x_m} y2={-b.local_y_m}
            stroke={flagged ? "#dc2626" : "#94a3b8"} strokeWidth={flagged ? 4 : 2} vectorEffect="non-scaling-stroke" />
        );
      })}
      {net.nodes.map((n) => {
        const flagged = !!n.asset_id && highlighted.has(n.asset_id);
        return (
          <circle key={n.node_id} cx={n.local_x_m} cy={-n.local_y_m} r={pad / 5} fill={color(n.node_type)}
            stroke={flagged ? "#dc2626" : "#ffffff"} strokeWidth={flagged ? 3 : 1} vectorEffect="non-scaling-stroke"
            className="cursor-pointer" onClick={() => onSelect(n)}>
            <title>{`${n.node_id} (${n.node_type})`}</title>
          </circle>
        );
      })}
    </svg>
  );
}

function NetworkMap({ net, highlighted }: { net: Network; highlighted: Set<string> }) {
  const ref = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<NetworkNode | null>(null);
  const [webgl] = useState(webglAvailable);
  useEffect(() => {
    if (!ref.current || !webgl) return;
    const byId = new Map(net.nodes.map((n) => [n.node_id, n]));
    const points: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: net.nodes.map((n) => ({
        type: "Feature",
        id: n.node_id,
        properties: {
          node_id: n.node_id,
          node_type: n.node_type,
          asset_id: n.asset_id ?? "",
          color: color(n.node_type),
          flagged: n.asset_id && highlighted.has(n.asset_id) ? 1 : 0,
        },
        geometry: { type: "Point", coordinates: toLngLat(n.local_x_m, n.local_y_m) },
      })),
    };
    const lines: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: net.edges
        .filter((e) => byId.has(e.from_node_id) && byId.has(e.to_node_id))
        .map((e) => {
          const a = byId.get(e.from_node_id)!;
          const b = byId.get(e.to_node_id)!;
          return {
            type: "Feature",
            properties: {
              edge_type: e.edge_type,
              flagged: e.element_asset_id && highlighted.has(e.element_asset_id) ? 1 : 0,
            },
            geometry: {
              type: "LineString",
              coordinates: [toLngLat(a.local_x_m, a.local_y_m), toLngLat(b.local_x_m, b.local_y_m)],
            },
          };
        }),
    };
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    const map = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": dark ? "#111827" : "#f4f6f9" } }],
      },
      attributionControl: false,
      renderWorldCopies: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      map.addSource("edges", { type: "geojson", data: lines });
      map.addSource("nodes", { type: "geojson", data: points });
      map.addLayer({
        id: "edges",
        type: "line",
        source: "edges",
        paint: {
          "line-color": ["case", ["==", ["get", "flagged"], 1], "#dc2626", dark ? "#64748b" : "#94a3b8"],
          "line-width": ["case", ["==", ["get", "flagged"], 1], 4, 2],
        },
      });
      map.addLayer({
        id: "nodes",
        type: "circle",
        source: "nodes",
        paint: {
          "circle-radius": 6,
          "circle-color": ["get", "color"],
          "circle-stroke-width": ["case", ["==", ["get", "flagged"], 1], 3, 1],
          "circle-stroke-color": ["case", ["==", ["get", "flagged"], 1], "#dc2626", "#ffffff"],
        },
      });
      const bounds = new maplibregl.LngLatBounds();
      net.nodes.forEach((n) => bounds.extend(toLngLat(n.local_x_m, n.local_y_m)));
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 40, duration: 0 });
      map.on("click", "nodes", (e) => {
        const id = e.features?.[0]?.properties?.node_id as string | undefined;
        setSelected(id ? byId.get(id) ?? null : null);
      });
      map.on("mouseenter", "nodes", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "nodes", () => (map.getCanvas().style.cursor = ""));
    });
    return () => map.remove();
  }, [net, highlighted, webgl]);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      {webgl ? (
        <div
          ref={ref}
          className="h-[560px] w-full overflow-hidden rounded-lg border"
          role="application"
          aria-label="Schematic map of the fictional AETHER Field gathering network. Use the node list for keyboard access."
        />
      ) : (
        <div className="space-y-1">
          <Schematic net={net} highlighted={highlighted} onSelect={setSelected} />
          <p className="text-[11px] text-muted-foreground">This browser has no WebGL, so a static schematic of the same network is shown.</p>
        </div>
      )}
      <div className="space-y-3">
        <Card>
          <CardHeader>
            <CardTitle>{selected ? selected.node_id : "Select a node"}</CardTitle>
            <CardDescription>
              {selected ? `${selected.node_type} at (${selected.local_x_m} m, ${selected.local_y_m} m)` : "Click a node on the map, or pick one below."}
            </CardDescription>
          </CardHeader>
          {selected?.asset_id && (
            <CardContent className="text-sm">
              <Link className="text-primary underline" to={`/assets/${selected.asset_id}`}>
                Open {selected.asset_id} in the Asset Explorer
              </Link>
              {highlighted.has(selected.asset_id) && (
                <p className="mt-1 text-xs text-destructive">Named as a candidate in a dispatching recommendation.</p>
              )}
            </CardContent>
          )}
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Legend</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-xs">
            {Array.from(new Set(net.nodes.map((n) => n.node_type))).map((t) => (
              <div key={t} className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-full" style={{ background: color(t) }} aria-hidden /> {t}
              </div>
            ))}
            <div className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-full border-2 border-red-600" aria-hidden /> candidate in a dispatching
              recommendation
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Nodes</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="max-h-56 space-y-0.5 overflow-auto text-xs">
              {net.nodes.map((n) => (
                <li key={n.node_id}>
                  <button className="w-full rounded px-1 py-0.5 text-left hover:bg-accent" onClick={() => setSelected(n)}>
                    {n.node_id} <span className="text-muted-foreground">{n.node_type}</span>
                  </button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function FieldMap() {
  const net = useQuery({ queryKey: ["network"], queryFn: () => request<Network>("/api/v1/network") });
  const recs = useQuery({
    queryKey: ["recommendations", "map"],
    queryFn: () => request<Paged<Recommendation>>("/api/v1/recommendations?limit=500"),
  });
  const highlighted = useMemo(
    () => new Set((recs.data?.items ?? []).filter((r) => r.priority_band).flatMap((r) => r.candidate_assets)),
    [recs.data],
  );
  return (
    <Page
      title="Field Map"
      description="The fictional gathering network from the database: wells, headers, gathering segments, and the compressor station, drawn in local metres."
    >
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge variant="warning">Schematic · local metres · no real location</Badge>
        <span className="text-muted-foreground">
          Real aerial imagery and plume detections are of real places, so they appear on the Aerial Inspection screen, never on this map.
        </span>
      </div>
      <QueryState q={net} isEmpty={(n) => n.nodes.length === 0} empty="No network is loaded. Run make field.">
        {(n) => <NetworkMap net={n} highlighted={highlighted} />}
      </QueryState>
    </Page>
  );
}
