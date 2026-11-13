import { useQuery } from "@tanstack/react-query";
import * as maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { Provenance, RealRecord, Status } from "@/components/badges";
import { webglAvailable } from "@/components/ErrorBoundary";
import { Page, Pager } from "@/components/Page";
import { Empty, QueryState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { query, request } from "@/lib/api";
import { num, when } from "@/lib/format";
import type { Source } from "@/lib/types";
import { cn } from "@/lib/utils";

type EvidenceRow = { evidence_id: string; source_asset_id: string; headline: string; coverage_status: string; plume_count: number; nearest_plume_m: number | null; chip_id: string | null; footprint_wgs84: [number, number, number, number] | null; reviewed: boolean; provenance: string };
type Inspections = {
  requests: { items: { request_id: string; asset_id: string; affected_asset_id: string; scenario_id: string; inspection_type: string; reason: string; status: string; created_at: string; provenance_class: string }[] };
  evidence: { source: Source; note: string; coverage_counts: Record<string, number>; total: number; limit: number; offset: number; items: EvidenceRow[] };
};
type Plume = { plume_id: string; observed_at: string; instrument: string; distance_m: number; wells_within_radius_of_plume: number; emission_kg_per_h: number | null; emission_uncertainty_kg_per_h: number | null; uncertainty_definition: string; caption: string };
type Evidence = {
  source_asset_id: string;
  headline: string;
  coverage_text: string;
  radius_m: number;
  chip_caption: string;
  attributions: string[];
  limits: string[];
  provenance: string;
  plumes: Plume[];
  chip: { chip_id: string; acquisition_date: string; ground_sample_distance_m: number; stac_item_id: string; sha256: string } | null;
  chip_url: string | null;
  reviews: { review_id: string; reviewer: string; outcome: string; visible_features: string[]; blinded_to_plume_status: boolean; recorded_at: string }[];
};

function FootprintMap({ rows, selected, onSelect }: { rows: EvidenceRow[]; selected: string | null; onSelect: (id: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [webgl] = useState(webglAvailable);
  useEffect(() => {
    if (!ref.current || !webgl) return;
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    const m = new maplibregl.Map({
      container: ref.current,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": dark ? "#111827" : "#eef1f5" } }] },
      attributionControl: false,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    return () => m.remove();
  }, [webgl]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const draw = () => {
      const features: GeoJSON.Feature[] = rows
        .filter((r) => r.footprint_wgs84)
        .map((r) => {
          const [w, s, e, n] = r.footprint_wgs84!;
          return {
            type: "Feature",
            properties: { id: r.evidence_id, near: r.coverage_status === "PLUME_NEARBY" ? 1 : 0, selected: r.evidence_id === selected ? 1 : 0 },
            geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
          };
        });
      const data: GeoJSON.FeatureCollection = { type: "FeatureCollection", features };
      const src = m.getSource("footprints") as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      else {
        m.addSource("footprints", { type: "geojson", data });
        m.addLayer({ id: "fp-fill", type: "fill", source: "footprints", paint: { "fill-color": ["case", ["==", ["get", "near"], 1], "#dc2626", "#3b6ea5"], "fill-opacity": 0.25 } });
        m.addLayer({ id: "fp-line", type: "line", source: "footprints", paint: { "line-color": ["case", ["==", ["get", "selected"], 1], "#111827", "#64748b"], "line-width": ["case", ["==", ["get", "selected"], 1], 3, 1] } });
        m.on("click", "fp-fill", (e) => {
          const id = e.features?.[0]?.properties?.id as string | undefined;
          if (id) onSelect(id);
        });
      }
      // The selected chip itself, placed on its real footprint.
      if (m.getLayer("chip")) m.removeLayer("chip");
      if (m.getSource("chip")) m.removeSource("chip");
      const row = rows.find((r) => r.evidence_id === selected);
      if (row?.chip_id && row.footprint_wgs84) {
        const [w, s, e, n] = row.footprint_wgs84;
        m.addSource("chip", { type: "image", url: `/api/v1/inspection-evidence/${row.chip_id}/chip.png`, coordinates: [[w, n], [e, n], [e, s], [w, s]] });
        m.addLayer({ id: "chip", type: "raster", source: "chip" }, "fp-line");
        m.fitBounds([[w, s], [e, n]], { padding: 60, duration: 300 });
      } else if (features.length) {
        const b = new maplibregl.LngLatBounds();
        features.forEach((f) => ((f.geometry as GeoJSON.Polygon).coordinates[0] as [number, number][]).forEach((c) => b.extend(c)));
        m.fitBounds(b, { padding: 30, duration: 0 });
      }
    };
    if (m.isStyleLoaded()) draw();
    else m.once("load", draw);
  }, [rows, selected, onSelect]);
  if (!webgl)
    return (
      <div className="flex h-[360px] items-center justify-center rounded-lg border p-4 text-center text-xs text-muted-foreground">
        This browser has no WebGL, so footprints can't be mapped. Select a location in the list to see its image and evidence.
      </div>
    );
  return <div ref={ref} className="h-[360px] w-full overflow-hidden rounded-lg border" role="application" aria-label="Image footprints of real registered well locations; use the list for keyboard access" />;
}

function EvidenceDetail({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["evidence", id], queryFn: () => request<Evidence>(`/api/v1/inspection-evidence/${encodeURIComponent(id)}`) });
  return (
    <QueryState q={q}>
      {(e) => (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">{e.headline} <RealRecord /></CardTitle>
            <CardDescription>
              Registered well <span className="font-mono">{e.source_asset_id}</span>. {e.coverage_text} Radius {num(e.radius_m)} m. {e.provenance}.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {e.chip_url && (
              <figure>
                <img src={e.chip_url} alt={`NAIP aerial image chip ${e.chip?.chip_id} around a registered well location`} className="max-h-72 rounded border" />
                <figcaption className="mt-1 text-[11px] text-muted-foreground">
                  {e.chip_caption} STAC item {e.chip?.stac_item_id}; SHA-256 {e.chip?.sha256.slice(0, 12)}…
                </figcaption>
              </figure>
            )}
            {e.plumes.length > 0 ? (
              <Table>
                <THead><TR><TH>Plume</TH><TH>Observed</TH><TH>Distance</TH><TH>Emission (kg/h)</TH><TH>Caption</TH></TR></THead>
                <TBody>
                  {e.plumes.map((p) => (
                    <TR key={p.plume_id}>
                      <TD className="font-mono">{p.plume_id}</TD>
                      <TD>{when(p.observed_at)}</TD>
                      <TD className="tabular-nums">{num(p.distance_m)} m</TD>
                      <TD className="tabular-nums" title={`Uncertainty definition: ${p.uncertainty_definition}`}>
                        {num(p.emission_kg_per_h)} ± {num(p.emission_uncertainty_kg_per_h)}
                        {p.uncertainty_definition === "UNKNOWN" && <span className="block text-[10px] text-muted-foreground">uncertainty basis not published</span>}
                      </TD>
                      <TD className="max-w-md">{p.caption}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            ) : (
              <p className="text-xs text-muted-foreground">No plume origin within the radius.</p>
            )}
            <div>
              <h3 className="text-xs font-semibold">Limits</h3>
              <ul className="mt-1 list-disc pl-5 text-xs">{e.limits.map((l) => <li key={l}>{l}</li>)}</ul>
            </div>
            <div>
              <h3 className="text-xs font-semibold">Operator annotations</h3>
              {e.reviews.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Awaiting blind review. Reviews are recorded with <code>make inspection-review</code>, where the reviewer sees the image without its plume status, so they are not taken on this screen.
                </p>
              ) : (
                <ul className="text-xs">
                  {e.reviews.map((r) => (
                    <li key={r.review_id}>
                      {when(r.recorded_at)} · {r.reviewer}: <strong>{r.outcome}</strong> {r.visible_features.join(", ")} {r.blinded_to_plume_status && <Badge variant="secondary">blind</Badge>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground">{e.attributions.join(" · ")}</p>
          </CardContent>
        </Card>
      )}
    </QueryState>
  );
}

export function AerialInspection() {
  const [coverage, setCoverage] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["inspections", coverage, offset],
    queryFn: () => request<Inspections>(`/api/v1/inspections${query({ coverage_status: coverage, limit: 20, offset })}`),
  });
  return (
    <Page
      title="Aerial Inspection"
      description="Two separate things: inspection requests for fictional AETHER assets, and Gate 6 evidence that links real public plume detections to real registered wells by proximity only."
    >
      <QueryState q={q}>
        {(d) => (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">Inspection requests <Provenance value="SYNTHETIC" /></CardTitle>
                <CardDescription>Requested for fictional assets from simulated scenario events.</CardDescription>
              </CardHeader>
              <CardContent>
                {d.requests.items.length === 0 ? (
                  <Empty>No inspection requests.</Empty>
                ) : (
                  <Table>
                    <THead><TR><TH>Request</TH><TH>Asset</TH><TH>Type</TH><TH>Status</TH><TH>Reason</TH></TR></THead>
                    <TBody>
                      {d.requests.items.map((r) => (
                        <TR key={r.request_id}>
                          <TD className="font-mono">{r.request_id}</TD>
                          <TD>{r.asset_id} (affected {r.affected_asset_id})</TD>
                          <TD>{r.inspection_type}</TD>
                          <TD><Status value={r.status} /></TD>
                          <TD className="max-w-lg">{r.reason}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">Aerial evidence <RealRecord /></CardTitle>
                <CardDescription>{d.evidence.note}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap items-end gap-3 text-xs">
                  <div className="space-y-1">
                    <Label htmlFor="coverage">Coverage</Label>
                    <Select id="coverage" value={coverage} onChange={(e) => { setCoverage(e.target.value); setOffset(0); setSelected(null); }} className="w-64">
                      <option value="">All ({Object.values(d.evidence.coverage_counts).reduce((a, b) => a + b, 0)})</option>
                      {Object.entries(d.evidence.coverage_counts).map(([k, v]) => (
                        <option key={k} value={k}>{k.replace(/_/g, " ").toLowerCase()} ({v})</option>
                      ))}
                    </Select>
                  </div>
                  <span className="text-muted-foreground">Source <code>{d.evidence.source.path}</code></span>
                </div>
                <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
                  <div className="space-y-2">
                    <ul className="max-h-[360px] space-y-1 overflow-auto" aria-label="Evidence locations">
                      {d.evidence.items.map((r) => (
                        <li key={r.evidence_id}>
                          <button
                            onClick={() => setSelected(r.evidence_id)}
                            aria-current={selected === r.evidence_id ? "true" : undefined}
                            className={cn("w-full rounded border px-2 py-1.5 text-left text-xs hover:bg-accent", selected === r.evidence_id && "border-primary bg-accent")}
                          >
                            <div className="font-medium">{r.headline}</div>
                            <div className="text-muted-foreground">
                              {r.source_asset_id} · {r.nearest_plume_m !== null ? `nearest plume ${num(r.nearest_plume_m)} m` : "no plume nearby"} · {r.reviewed ? "reviewed" : "not reviewed"}
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                    <Pager total={d.evidence.total} limit={d.evidence.limit} offset={d.evidence.offset} onChange={setOffset} />
                  </div>
                  <FootprintMap rows={d.evidence.items} selected={selected} onSelect={setSelected} />
                </div>
                <p className="text-[11px] text-muted-foreground">Footprints are drawn at their real positions with no basemap loaded. Red: a plume origin lies within the radius. Blue: imaged, no plume nearby.</p>
              </CardContent>
            </Card>
            {selected && <EvidenceDetail id={selected} />}
          </>
        )}
      </QueryState>
    </Page>
  );
}
