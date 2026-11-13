import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ActorKind, Band, Status } from "@/components/badges";
import { EChart } from "@/components/EChart";
import { useMe } from "@/components/Layout";
import { Page, Pager } from "@/components/Page";
import { Empty, ErrorState, QueryState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { newIdempotencyKey, query, request, type Paged } from "@/lib/api";
import { num, usd, when } from "@/lib/format";
import type { Source, Stats, WorkOrder } from "@/lib/types";

type Economics = {
  label: string;
  horizon_days: number;
  replicates: number;
  policies: Record<string, Record<string, Stats>>;
  sensitivity: { assumption: string; factor: number; cheapest: string; route_minus_risk_based_mean: number }[];
  source: Source;
};

const ACTIONS: Record<string, { verb: string; path: string; label: string; roles: string[]; variant?: "destructive" | "outline" }[]> = {
  RECOMMENDED: [
    { verb: "APPROVE", path: "approve", label: "Approve", roles: ["MAINTENANCE_SUPERVISOR"] },
    { verb: "REQUEST_EVIDENCE", path: "request-evidence", label: "Request evidence", roles: ["MAINTENANCE_SUPERVISOR"], variant: "outline" },
    { verb: "REJECT", path: "reject", label: "Reject", roles: ["MAINTENANCE_SUPERVISOR"], variant: "destructive" },
  ],
  NEEDS_EVIDENCE: [{ verb: "REJECT", path: "reject", label: "Reject", roles: ["MAINTENANCE_SUPERVISOR"], variant: "destructive" }],
  APPROVED: [{ verb: "COMPLETE", path: "complete", label: "Record simulated visit complete", roles: ["OPERATOR", "MAINTENANCE_SUPERVISOR"] }],
};

function Decide({ order }: { order: WorkOrder }) {
  const me = useMe();
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const decide = useMutation({
    mutationFn: (path: string) =>
      request<WorkOrder>(`/api/v1/work-orders/${encodeURIComponent(order.work_order_id)}/${path}`, {
        method: "POST",
        body: { justification: text.trim() },
        idempotencyKey: key,
      }),
    onSuccess: () => {
      setText("");
      setKey(newIdempotencyKey());
      ["work-orders", "recommendations", "overview", "audit"].forEach((k) => client.invalidateQueries({ queryKey: [k] }));
    },
  });
  const options = ACTIONS[order.status] ?? [];
  if (options.length === 0) return <p className="text-xs text-muted-foreground">No further decision is possible from {order.status.toLowerCase()}.</p>;
  const role = me.data?.role;
  return (
    <div className="space-y-2">
      <Label htmlFor={`j-${order.work_order_id}`}>Justification (recorded with your decision)</Label>
      <Textarea id={`j-${order.work_order_id}`} value={text} onChange={(e) => { setText(e.target.value); setKey(newIdempotencyKey()); }} placeholder="What you reviewed and why" />
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <Button key={o.verb} size="sm" variant={o.variant} disabled={!role || !o.roles.includes(role) || !text.trim() || decide.isPending} onClick={() => decide.mutate(o.path)} title={role && !o.roles.includes(role) ? `Needs ${o.roles.join(" or ")}` : undefined}>
            {o.label}
          </Button>
        ))}
      </div>
      {!role && <p className="text-[11px] text-muted-foreground">Sign in to decide. Approvals need a maintenance supervisor; the database refuses them from any other role.</p>}
      {decide.isError && <ErrorState error={decide.error} />}
    </div>
  );
}

function Timeline({ order }: { order: WorkOrder }) {
  return (
    <ol className="space-y-2 border-l pl-4">
      {order.transitions.map((t) => (
        <li key={t.sequence} className="relative text-xs">
          <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full border-2 border-card bg-primary" aria-hidden />
          <div className="flex flex-wrap items-center gap-2">
            <strong>{t.decision.replace(/_/g, " ")}</strong>
            <span className="text-muted-foreground">{t.from_status ?? "—"} → {t.to_status}</span>
            <ActorKind kind={t.actor_kind} />
            <span>{t.actor_id} ({t.actor_role.replace(/_/g, " ").toLowerCase()})</span>
          </div>
          <p className="mt-0.5">{t.justification}</p>
          <p className="text-[11px] text-muted-foreground">scenario clock {when(t.decided_at)} · recorded {when(t.recorded_at)}</p>
        </li>
      ))}
    </ol>
  );
}

function RouteComparison() {
  const q = useQuery({ queryKey: ["economics"], queryFn: () => request<Economics>("/api/v1/economics/comparison") });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Route and policy comparison (modeled)</CardTitle>
        <CardDescription>Fixed rounds, risk-based dispatch, and route-optimised dispatch over a modeled year.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState q={q}>
          {(e) => {
            const names = Object.keys(e.policies);
            const row = (metric: string, f: (v: number) => string) => (
              <TR key={metric}>
                <TD>{metric.replace(/_/g, " ")}</TD>
                {names.map((n) => <TD key={n} className="tabular-nums">{e.policies[n][metric] ? `${f(e.policies[n][metric].mean)} (${f(e.policies[n][metric].p5)} to ${f(e.policies[n][metric].p95)})` : "—"}</TD>)}
              </TR>
            );
            return (
              <div className="space-y-3">
                <p className="text-xs font-medium text-warning">{e.label}</p>
                <EChart
                  label="Modeled annual total cost by policy, mean with 5th to 95th percentile"
                  height={220}
                  option={{
                    grid: { left: 80, right: 20, top: 10, bottom: 30 },
                    xAxis: { type: "category", data: names, axisLabel: { interval: 0, fontSize: 10 } },
                    yAxis: {
                      type: "value",
                      // Scale to the whiskers, not just the bars, so no percentile is clipped.
                      max: Math.max(...names.map((n) => e.policies[n].total.p95)) * 1.05,
                      axisLabel: { formatter: (v: number) => `$${Math.round(v / 1000)}k` },
                    },
                    tooltip: { trigger: "axis", valueFormatter: (v) => usd(v as number) },
                    series: [
                      { type: "bar", name: "mean", data: names.map((n) => e.policies[n].total.mean), itemStyle: { color: "#3b6ea5" } },
                      { type: "custom", name: "5th to 95th", renderItem: (_p: unknown, api: any) => {
                        const i = api.value(0); const lo = api.coord([i, api.value(1)]); const hi = api.coord([i, api.value(2)]);
                        return { type: "group", children: [
                          { type: "line", shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] }, style: { stroke: "#334155", lineWidth: 1.5 } },
                          { type: "line", shape: { x1: lo[0] - 8, y1: lo[1], x2: lo[0] + 8, y2: lo[1] }, style: { stroke: "#334155" } },
                          { type: "line", shape: { x1: hi[0] - 8, y1: hi[1], x2: hi[0] + 8, y2: hi[1] }, style: { stroke: "#334155" } },
                        ] };
                      }, data: names.map((n, i) => [i, e.policies[n].total.p5, e.policies[n].total.p95]) } as never,
                    ],
                  }}
                />
                <Table>
                  <THead><TR><TH>Mean (5th to 95th percentile)</TH>{names.map((n) => <TH key={n}>{n}</TH>)}</TR></THead>
                  <TBody>
                    {row("total", usd)}
                    {row("travel_km", (v) => num(v))}
                    {row("site_visits", (v) => num(v))}
                    {row("trips_finding_nothing", (v) => num(v))}
                    {row("deferred_mcf", (v) => num(v))}
                    {row("mean_hours_to_repair", (v) => num(v))}
                  </TBody>
                </Table>
                <p className="text-[11px] text-muted-foreground">
                  {e.replicates} replicates over {e.horizon_days} days. Source <code>{e.source.path}</code>. Technician assignment is not modeled: work orders carry no crew field, and crews appear only as travel and labour in this model.
                </p>
              </div>
            );
          }}
        </QueryState>
      </CardContent>
    </Card>
  );
}

export function Maintenance() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const selected = params.get("wo");
  const q = useQuery({
    queryKey: ["work-orders", status, offset],
    queryFn: () => request<Paged<WorkOrder> & { note: string }>(`/api/v1/work-orders${query({ status, limit: 25, offset })}`),
  });
  const order = q.data?.items.find((o) => o.work_order_id === selected) ?? null;
  return (
    <Page title="Maintenance" description="Simulated work orders, their approval workflow, and the modeled route comparison. Every transition is checked by the database and audited.">
      <div className="grid gap-4 xl:grid-cols-[1fr_440px]">
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <CardTitle>Work orders</CardTitle>
                <CardDescription>{q.data?.note}</CardDescription>
              </div>
              <div className="space-y-1">
                <Label htmlFor="status">Status</Label>
                <Select id="status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className="w-44">
                  <option value="">All</option>
                  {["RECOMMENDED", "NEEDS_EVIDENCE", "APPROVED", "REJECTED", "COMPLETED"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ").toLowerCase()}</option>)}
                </Select>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            <QueryState q={q} isEmpty={(p) => p.total === 0} empty={<>No work orders{status ? " with this status" : ""}. Open one from the <Link className="underline" to="/decisions">Decision Center</Link>.</>}>
              {(p) => (
                <>
                  <Table>
                    <THead><TR><TH>Work order</TH><TH>Asset</TH><TH>Band</TH><TH>Status</TH><TH>Decided by</TH><TH>Created (scenario clock)</TH></TR></THead>
                    <TBody>
                      {p.items.map((o) => (
                        <TR key={o.work_order_id} data-selected={o.work_order_id === selected} className="cursor-pointer" onClick={() => setParams({ wo: o.work_order_id })}>
                          <TD><button className="font-mono text-primary underline" onClick={() => setParams({ wo: o.work_order_id })}>{o.work_order_id}</button></TD>
                          <TD>{o.asset_id}</TD>
                          <TD><Band value={o.priority_band} /></TD>
                          <TD><Status value={o.status} /></TD>
                          <TD className="space-x-1">{o.decided_by_kinds.length ? o.decided_by_kinds.map((k) => <ActorKind key={k} kind={k} />) : "—"}</TD>
                          <TD>{when(o.created_at)}</TD>
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
        <Card>
          <CardHeader>
            <CardTitle>{order ? order.work_order_id : "Select a work order"}</CardTitle>
            {order && <CardDescription>{order.recommended_action.replace(/_/g, " ").toLowerCase()} at {order.asset_id} · {order.scenario_id} · from {order.recommendation_id}</CardDescription>}
          </CardHeader>
          <CardContent className="space-y-4">
            {order ? (
              <>
                <Timeline order={order} />
                <Decide order={order} />
              </>
            ) : (
              <Empty>Pick a work order to see its history and decide on it.</Empty>
            )}
          </CardContent>
        </Card>
      </div>
      <RouteComparison />
    </Page>
  );
}
