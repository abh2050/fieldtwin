import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ActorKind, Status } from "@/components/badges";
import { EChart } from "@/components/EChart";
import { Page, Stat } from "@/components/Page";
import { Empty, QueryState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { request } from "@/lib/api";
import { pct, usd } from "@/lib/format";
import type { Source } from "@/lib/types";

type OverviewData = {
  counts: Record<string, number>;
  work_order_backlog: { status: string; n: number }[];
  decisions_by_actor_kind: { actor_kind: string; n: number }[];
  economics: { label: string; mean_total: Record<string, number>; source: Source } | null;
  detection: {
    method: string;
    events_detected: number;
    events: number;
    event_recall: number;
    chance_event_recall: number;
    source: Source;
  } | null;
  d1_outcome: string | null;
};

function Finding({ gate, title, slug, children, badge }: {
  gate: string;
  title: string;
  slug: string;
  children: React.ReactNode;
  badge?: React.ReactNode;
}) {
  return (
    <div className="text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{gate}</Badge>
        <span className="font-medium">{title}</span>
        {badge}
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{children}</p>
      <Link to={`/reports?report=${slug}`} className="text-xs text-primary underline">
        Read the report
      </Link>
    </div>
  );
}

export function Overview() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => request<OverviewData>("/api/v1/overview") });
  return (
    <Page
      title="Overview"
      description="Facility and scenario status for fictional AETHER Field, and what the experiments found. Every number is a database count or a value read from a committed result file."
    >
      <QueryState q={q}>
        {(d) => {
          const totals = d.economics ? Object.entries(d.economics.mean_total) : [];
          const cheapest = totals.length ? totals.reduce((a, b) => (b[1] < a[1] ? b : a)) : null;
          return (
            <>
              <section
                aria-label="Facility and scenario status"
                className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7"
              >
                <Stat label="Fictional assets" value={d.counts.fictional_assets} />
                <Stat label="Scenarios" value={d.counts.scenarios} note={`${d.counts.scenario_runs} stored runs`} />
                <Stat label="Detector alarms" value={d.counts.alarms} note="on simulated runs" />
                <Stat label="Dispatching recommendations" value={d.counts.dispatching_recommendations} />
                <Stat label="Pending inspections" value={d.counts.pending_inspections} />
                <Stat label="Open data-quality exceptions" value={d.counts.open_quality_exceptions} />
                <Stat label="Real public sources" value={d.counts.real_sources} />
              </section>

              <div className="grid gap-4 lg:grid-cols-3">
                <Card>
                  <CardHeader>
                    <CardTitle>Maintenance backlog</CardTitle>
                    <CardDescription>Simulated work orders by status.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {d.work_order_backlog.length === 0 ? (
                      <Empty>
                        No work orders yet. Open one from a recommendation in the{" "}
                        <Link className="underline" to="/decisions">
                          Decision Center
                        </Link>
                        .
                      </Empty>
                    ) : (
                      d.work_order_backlog.map((b) => (
                        <div key={b.status} className="flex items-center justify-between text-sm">
                          <Status value={b.status} /> <span className="tabular-nums">{b.n}</span>
                        </div>
                      ))
                    )}
                    {d.decisions_by_actor_kind.length > 0 && (
                      <div className="border-t pt-2 text-xs text-muted-foreground">
                        Decisions recorded:{" "}
                        {d.decisions_by_actor_kind.map((k) => (
                          <span key={k.actor_kind} className="mr-2 inline-flex items-center gap-1">
                            <ActorKind kind={k.actor_kind} /> {k.n}
                          </span>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Modeled annual cost by policy</CardTitle>
                    <CardDescription>{d.economics?.label ?? "Economics not built."}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {d.economics ? (
                      <>
                        <EChart
                          label="Mean modeled annual cost for each maintenance policy"
                          height={200}
                          option={{
                            grid: { left: 70, right: 10, top: 10, bottom: 30 },
                            xAxis: {
                              type: "category",
                              data: totals.map(([k]) => k),
                              axisLabel: { interval: 0, fontSize: 10, formatter: (v: string) => v.replace("_", "\n") },
                            },
                            yAxis: {
                              type: "value",
                              axisLabel: { formatter: (v: number) => `$${Math.round(v / 1000)}k` },
                            },
                            tooltip: { trigger: "axis", valueFormatter: (v) => usd(v as number) },
                            series: [{ type: "bar", data: totals.map(([, v]) => v), itemStyle: { color: "#3b6ea5" } }],
                          }}
                        />
                        <p className="text-[11px] text-muted-foreground">
                          Mean over replicates. Source <code>{d.economics.source.path}</code>.
                        </p>
                      </>
                    ) : (
                      <Empty>
                        Run <code>make decision-economics</code> to build it.
                      </Empty>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>What the experiments found</CardTitle>
                    <CardDescription>Negative results are shown as prominently as positive ones.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Finding gate="Gate 5" title="Detection is weak" slug="detection">
                      {d.detection
                        ? `The selected detector (${d.detection.method}) caught ${d.detection.events_detected} of ${d.detection.events} held-out events: event recall ${pct(d.detection.event_recall)}, against ${pct(d.detection.chance_event_recall)} by chance.`
                        : "Detection results are not built."}
                    </Finding>
                    <Finding gate="Gate 7" title="Alarm-driven dispatch did not pay in the model" slug="economics">
                      {cheapest
                        ? `The cheapest policy on mean modeled cost was ${cheapest[0]} (${usd(cheapest[1])} a year). These are model estimates for a fictional field, not savings.`
                        : "Economics are not built."}
                    </Finding>
                    <Finding
                      gate="D1"
                      title="Model-based restriction diagnosis"
                      slug="d1"
                      badge={
                        d.d1_outcome ? <Badge variant="destructive">{d.d1_outcome.replace("_", " ")}</Badge> : null
                      }
                    >
                      Preregistered, frozen, and evaluated once. See the report for which acceptance lines failed.
                    </Finding>
                  </CardContent>
                </Card>
              </div>
            </>
          );
        }}
      </QueryState>
    </Page>
  );
}
