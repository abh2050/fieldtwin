import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Provenance, Status } from "@/components/badges";
import { KV, Page, Pager } from "@/components/Page";
import { Empty, QueryState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { query, request, type Paged } from "@/lib/api";
import { num } from "@/lib/format";
import type { Asset, AssetDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

type Relationships = {
  declared: { relationship_id: number; source_asset_id: string; target_asset_id: string; relationship_type: string; evidence_type: string; provenance_class: string; effective_from: string | null; effective_to: string | null }[];
  physical: { edge_id: string; edge_type: string; from_asset_id: string | null; to_asset_id: string | null; element_asset_id: string | null; length_m: number | null; diameter_m: number | null }[];
};
type Observation = { observation_id: number; metric_name: string; unit_id: string; quality_flag: string; provenance_class: string; value_count: number; null_count: number; scenario_run_id: string | null; original_record_uri: string };

function Tree({ assets, selected, onSelect }: { assets: Asset[]; selected?: string; onSelect: (id: string) => void }) {
  const children = useMemo(() => {
    const m = new Map<string | null, Asset[]>();
    for (const a of assets) m.set(a.parent_asset_id, [...(m.get(a.parent_asset_id) ?? []), a]);
    return m;
  }, [assets]);
  const ids = new Set(assets.map((a) => a.asset_id));
  const roots = assets.filter((a) => !a.parent_asset_id || !ids.has(a.parent_asset_id));
  const render = (a: Asset, depth: number): React.ReactNode => (
    <li key={a.asset_id}>
      <button
        onClick={() => onSelect(a.asset_id)}
        aria-current={selected === a.asset_id ? "true" : undefined}
        className={cn("flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-left text-xs hover:bg-accent", selected === a.asset_id && "bg-accent font-medium")}
        style={{ paddingLeft: 6 + depth * 14 }}
      >
        <span>{a.asset_id}</span>
        <span className="text-muted-foreground">{a.asset_type.toLowerCase()}</span>
      </button>
      {(children.get(a.asset_id) ?? []).length > 0 && <ul>{children.get(a.asset_id)!.map((c) => render(c, depth + 1))}</ul>}
    </li>
  );
  return <ul aria-label="Asset hierarchy">{roots.map((r) => render(r, 0))}</ul>;
}

function Detail({ assetId }: { assetId: string }) {
  const [offset, setOffset] = useState(0);
  const detail = useQuery({ queryKey: ["asset", assetId], queryFn: () => request<AssetDetail>(`/api/v1/assets/${encodeURIComponent(assetId)}`) });
  const rel = useQuery({ queryKey: ["asset-rel", assetId], queryFn: () => request<Relationships>(`/api/v1/assets/${encodeURIComponent(assetId)}/relationships`) });
  const obs = useQuery({
    queryKey: ["asset-obs", assetId, offset],
    queryFn: () => request<Paged<Observation>>(`/api/v1/assets/${encodeURIComponent(assetId)}/observations${query({ limit: 25, offset })}`),
  });
  return (
    <div className="space-y-4">
      <QueryState q={detail}>
        {(a) => (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {a.asset_name} <Provenance value={a.provenance_class} />
              </CardTitle>
              <CardDescription>Fictional asset {a.asset_id}. Nothing here describes a real well or facility.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <KV
                rows={[
                  ["Type", a.asset_type],
                  ["Equipment class", a.equipment_class_id],
                  ["Parent", a.parent_asset_id],
                  ["Children", a.children.join(", ") || "none"],
                  ["Operating status", a.operating_status],
                  ["Transformation", a.transformation_id],
                  ["Network nodes", a.network_nodes.map((n) => n.node_id).join(", ") || "none"],
                ]}
              />
              <div>
                <h3 className="mb-1 text-xs font-semibold">Work orders</h3>
                {a.work_orders.length === 0 ? (
                  <p className="text-xs text-muted-foreground">None for this asset.</p>
                ) : (
                  <ul className="space-y-1 text-xs">
                    {a.work_orders.map((w) => (
                      <li key={w.external_id} className="flex items-center gap-2">
                        <Link className="text-primary underline" to={`/maintenance?wo=${w.external_id}`}>{w.external_id}</Link>
                        <Status value={w.status} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="md:col-span-2">
                <h3 className="mb-1 text-xs font-semibold">Sensors ({a.sensors.length})</h3>
                {a.sensors.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No simulated sensors on this asset.</p>
                ) : (
                  <Table>
                    <THead><TR><TH>Tag</TH><TH>Quantity</TH><TH>Unit</TH><TH>Pressure reference</TH><TH>Sampling</TH></TR></THead>
                    <TBody>
                      {a.sensors.map((s) => (
                        <TR key={s.tag_id}><TD className="font-mono">{s.native_tag_name}</TD><TD>{s.physical_quantity}</TD><TD>{s.unit_id}</TD><TD>{s.pressure_reference_type}</TD><TD>{s.sampling_frequency}</TD></TR>
                      ))}
                    </TBody>
                  </Table>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </QueryState>
      <Card>
        <CardHeader>
          <CardTitle>Relationships</CardTitle>
          <CardDescription>Declared hierarchy relationships, and physical pipe connections from the network model.</CardDescription>
        </CardHeader>
        <CardContent>
          <QueryState q={rel}>
            {(r) =>
              r.declared.length + r.physical.length === 0 ? (
                <Empty>No relationships recorded for this asset.</Empty>
              ) : (
                <Table>
                  <THead><TR><TH>Kind</TH><TH>Type</TH><TH>From</TH><TH>To</TH><TH>Detail</TH></TR></THead>
                  <TBody>
                    {r.declared.map((d) => (
                      <TR key={`d${d.relationship_id}`}><TD>declared</TD><TD>{d.relationship_type}</TD><TD>{d.source_asset_id}</TD><TD>{d.target_asset_id}</TD><TD>{d.evidence_type} <Provenance value={d.provenance_class} /></TD></TR>
                    ))}
                    {r.physical.map((p) => (
                      <TR key={p.edge_id}><TD>physical</TD><TD>{p.edge_type}</TD><TD>{p.from_asset_id ?? "—"}</TD><TD>{p.to_asset_id ?? "—"}</TD><TD>{p.length_m ? `${num(p.length_m)} m` : ""}{p.diameter_m ? ` · ⌀ ${p.diameter_m} m` : ""}</TD></TR>
                    ))}
                  </TBody>
                </Table>
              )
            }
          </QueryState>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Operating history</CardTitle>
          <CardDescription>Stored series for this asset's sensors, one row per sensor and scenario run. Open a series in the Telemetry Lab.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <QueryState q={obs} isEmpty={(p) => p.total === 0} empty="No stored series for this asset.">
            {(p) => (
              <>
                <Table>
                  <THead><TR><TH>Series</TH><TH>Run</TH><TH>Values</TH><TH>Missing</TH><TH>Quality</TH><TH>Lineage</TH></TR></THead>
                  <TBody>
                    {p.items.map((o) => (
                      <TR key={o.observation_id}>
                        <TD className="font-mono">{o.metric_name}</TD>
                        <TD>
                          {o.scenario_run_id ? (
                            <Link className="text-primary underline" to={`/telemetry?run=${encodeURIComponent(o.scenario_run_id)}&tag=${encodeURIComponent(o.metric_name)}`}>{o.scenario_run_id}</Link>
                          ) : "—"}
                        </TD>
                        <TD className="tabular-nums">{num(o.value_count)}</TD>
                        <TD className="tabular-nums">{num(o.null_count)}</TD>
                        <TD>{o.quality_flag}</TD>
                        <TD><Link className="text-primary underline" to={`/lineage?record=observation:${o.observation_id}`}>trace</Link></TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
                <Pager total={p.total} limit={p.limit} offset={p.offset} onChange={setOffset} />
              </>
            )}
          </QueryState>
        </CardContent>
      </Card>
    </div>
  );
}

export function AssetExplorer() {
  const { assetId } = useParams();
  const navigate = useNavigate();
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const all = useQuery({ queryKey: ["assets", "all"], queryFn: () => request<Paged<Asset>>("/api/v1/assets?limit=500") });
  const types = useMemo(() => Array.from(new Set((all.data?.items ?? []).map((a) => a.asset_type))).sort(), [all.data]);
  const filtered = (all.data?.items ?? []).filter(
    (a) => (!type || a.asset_type === type) && (!search || `${a.asset_id} ${a.asset_name}`.toLowerCase().includes(search.toLowerCase())),
  );
  return (
    <Page title="Asset Explorer" description="The fictional AETHER asset hierarchy, equipment details, sensors, operating history, provenance, and relationships.">
      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Assets</CardTitle>
            <div className="flex gap-2 pt-1">
              <label className="sr-only" htmlFor="asset-search">Search assets</label>
              <Input id="asset-search" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} className="h-8 text-xs" />
              <label className="sr-only" htmlFor="asset-type">Asset type</label>
              <Select id="asset-type" value={type} onChange={(e) => setType(e.target.value)} className="h-8 w-32 text-xs">
                <option value="">All types</option>
                {types.map((t) => <option key={t}>{t}</option>)}
              </Select>
            </div>
          </CardHeader>
          <CardContent className="max-h-[70vh] overflow-auto">
            <QueryState q={all} isEmpty={(p) => p.total === 0} empty="No assets loaded. Run make field.">
              {() =>
                filtered.length === 0 ? (
                  <Empty>No asset matches these filters.</Empty>
                ) : type || search ? (
                  <ul>
                    {filtered.map((a) => (
                      <li key={a.asset_id}>
                        <button onClick={() => navigate(`/assets/${a.asset_id}`)} className={cn("w-full rounded px-1.5 py-0.5 text-left text-xs hover:bg-accent", assetId === a.asset_id && "bg-accent")}>
                          {a.asset_id} <span className="text-muted-foreground">{a.asset_type.toLowerCase()}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Tree assets={filtered} selected={assetId} onSelect={(id) => navigate(`/assets/${id}`)} />
                )
              }
            </QueryState>
            {all.data && <p className="mt-2 text-[11px] text-muted-foreground">{all.data.total} fictional assets</p>}
          </CardContent>
        </Card>
        {assetId ? <Detail assetId={assetId} /> : <Empty>Select an asset to see its details.</Empty>}
      </div>
    </Page>
  );
}
