import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import { useSearchParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { KV, Page } from "@/components/Page";
import { Empty, QueryState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { request } from "@/lib/api";
import { interval, num, pct, short } from "@/lib/format";
import type { Source } from "@/lib/types";
import { cn } from "@/lib/utils";

type CatalogEntry = { slug: string; gate: string; title: string; path: string; outcome: string; available: boolean };
// A value is a number, an interval [low, high], or an estimate with its interval [value, [low, high]].
type Line = { line: string; value: number | [number, number] | [number, [number, number]] | null; rule: string; status: string };
type D1 = {
  outcome: { outcome: string; failed_in_regime_lines: string[] };
  in_regime: { acceptance: Line[]; cases_in_manifest: number; freeze_method_commit: string; preregistration_version: number };
  held_out: { acceptance: Line[] | Record<string, Line[]>; metrics_by_regime: Record<string, { top1: number; coverage_80: { severity: number; impact: number }; joint_success_rate: number; b1_top1?: number }> };
  note: string;
  sources: Source[];
};
type MethodRow = { method: string; event_recall: number; event_recall_interval: [number, number] | null; chance_event_recall: number; event_skill: number; false_alarms_per_hour: number; average_precision: number };
type Evaluations = {
  selected_method: string;
  track: string;
  reproducibility: { git_sha: string; hardware: Record<string, unknown>; dataset_sha256: string; parameter_sets_sha256: string; cases: number };
  compute: { hardware: Record<string, unknown>; rows: { model: string; window_latency_ms: { p50: number; p95: number; p99: number }; load_seconds: number; process_peak_rss_mb: number; artifact_bytes: number; batch_stream_agree: boolean }[]; source: Source } | null;
  in_regime: { methods: MethodRow[]; source: Source };
  held_out: { pooled: MethodRow[]; source: Source };
};

const OUTCOME: Record<string, { text: string; variant: "destructive" | "warning" | "secondary" | "default" }> = {
  NOT_MET: { text: "NOT MET", variant: "destructive" },
  WEAK: { text: "weak", variant: "warning" },
  RISK_BASED_LOST: { text: "risk-based lost", variant: "warning" },
  PROXIMITY_ONLY: { text: "proximity only", variant: "secondary" },
  RECORDED: { text: "recorded", variant: "default" },
};

function fmt(v: Line["value"]) {
  if (v === null) return "—";
  if (Array.isArray(v) && Array.isArray(v[1])) return `${num(v[0] as number, 3)} (${interval(v[1], 3)})`;
  if (Array.isArray(v)) return interval(v, 3);
  return num(v, 3);
}

function D1Summary() {
  const q = useQuery({ queryKey: ["d1"], queryFn: () => request<D1>("/api/v1/diagnostics/d1") });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">D1: gathering-line restriction diagnosis <Badge variant="destructive">{q.data?.outcome.outcome.replace("_", " ") ?? "…"}</Badge></CardTitle>
        <CardDescription>{q.data?.note}</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState q={q}>
          {(d) => (
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <h3 className="mb-1 text-xs font-semibold">In-regime acceptance ({d.in_regime.cases_in_manifest} cases, preregistration v{d.in_regime.preregistration_version}, method {short(d.in_regime.freeze_method_commit, 7)})</h3>
                <Table>
                  <THead><TR><TH>Line</TH><TH>Value</TH><TH>Rule</TH><TH>Status</TH></TR></THead>
                  <TBody>
                    {d.in_regime.acceptance.map((l) => (
                      <TR key={l.line} className={cn(l.status === "FAIL" && "bg-destructive/10 font-medium")}>
                        <TD>{l.line.replace(/_/g, " ")}</TD><TD className="tabular-nums">{fmt(l.value)}</TD><TD>{l.rule}</TD>
                        <TD><Badge variant={l.status === "PASS" ? "success" : l.status === "FAIL" ? "destructive" : "secondary"}>{l.status}</Badge></TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold">Held-out regimes</h3>
                <Table>
                  <THead><TR><TH>Regime</TH><TH>Top-1</TH><TH>80% coverage, severity / impact</TH><TH>Joint success</TH><TH>Baseline top-1</TH></TR></THead>
                  <TBody>
                    {Object.entries(d.held_out.metrics_by_regime).map(([name, m]) => (
                      <TR key={name}>
                        <TD>{name.replace(/_/g, " ")}</TD>
                        <TD className={cn("tabular-nums", m.top1 < 0.55 && "font-semibold text-destructive")}>{num(m.top1, 3)}</TD>
                        <TD className={cn("tabular-nums", (m.coverage_80.severity < 0.65 || m.coverage_80.impact < 0.65) && "font-semibold text-destructive")}>{num(m.coverage_80.severity, 3)} / {num(m.coverage_80.impact, 3)}</TD>
                        <TD className="tabular-nums">{num(m.joint_success_rate, 3)}</TD>
                        <TD className="tabular-nums">{m.b1_top1 !== undefined ? num(m.b1_top1, 3) : "—"}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
                <p className="mt-1 text-[11px] text-muted-foreground">Red marks a value outside its preregistered held-out band (top-1 at least 0.55; 80% coverage 0.65 to 0.92). The full rules are in the report.</p>
              </div>
            </div>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function Detection() {
  const q = useQuery({ queryKey: ["evaluations"], queryFn: () => request<Evaluations>("/api/v1/model-evaluations") });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Gate 5 model comparison</CardTitle>
        <CardDescription>Event recall in the training regime against held-out regimes, with chance for comparison. A drop from left to right is the generalisation gap.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState q={q}>
          {(e) => {
            const held = new Map(e.held_out.pooled.map((m) => [m.method, m]));
            return (
              <div className="space-y-4">
                <Table>
                  <THead><TR><TH>Method</TH><TH>In-regime recall</TH><TH>Held-out recall (95%)</TH><TH>Held-out chance</TH><TH>Held-out false alarms / h</TH><TH>Held-out average precision</TH></TR></THead>
                  <TBody>
                    {e.in_regime.methods.map((m) => {
                      const h = held.get(m.method);
                      return (
                        <TR key={m.method} data-selected={m.method === e.selected_method}>
                          <TD>{m.method}{m.method === e.selected_method && <Badge className="ml-1">selected</Badge>}</TD>
                          <TD className="tabular-nums">{pct(m.event_recall)}</TD>
                          <TD className="tabular-nums">{h ? `${pct(h.event_recall)} (${interval(h.event_recall_interval)})` : "—"}</TD>
                          <TD className="tabular-nums">{h ? pct(h.chance_event_recall) : "—"}</TD>
                          <TD className="tabular-nums">{h ? num(h.false_alarms_per_hour, 4) : "—"}</TD>
                          <TD className="tabular-nums">{h ? num(h.average_precision, 3) : "—"}</TD>
                        </TR>
                      );
                    })}
                  </TBody>
                </Table>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h3 className="mb-1 text-xs font-semibold">Reproducibility</h3>
                    <KV rows={[
                      ["Commit", e.reproducibility.git_sha],
                      ["Cases", e.reproducibility.cases],
                      ["Dataset SHA-256", short(e.reproducibility.dataset_sha256, 16)],
                      ["Parameter sets SHA-256", short(e.reproducibility.parameter_sets_sha256, 16)],
                      ["Hardware", Object.entries(e.reproducibility.hardware ?? {}).map(([k, v]) => `${k} ${v}`).join(", ")],
                      ["Sources", `${e.in_regime.source.path}, ${e.held_out.source.path}`],
                    ]} />
                  </div>
                  <div>
                    <h3 className="mb-1 text-xs font-semibold">Compute performance</h3>
                    {e.compute ? (
                      <Table>
                        <THead><TR><TH>Model</TH><TH>Window latency p50 / p95 / p99 (ms)</TH><TH>Peak RSS</TH><TH>Batch = stream</TH></TR></THead>
                        <TBody>
                          {e.compute.rows.map((r) => (
                            <TR key={r.model}><TD>{r.model}</TD><TD className="tabular-nums">{num(r.window_latency_ms.p50, 2)} / {num(r.window_latency_ms.p95, 2)} / {num(r.window_latency_ms.p99, 2)}</TD><TD className="tabular-nums">{num(r.process_peak_rss_mb)} MB</TD><TD>{r.batch_stream_agree ? "yes" : "no"}</TD></TR>
                          ))}
                        </TBody>
                      </Table>
                    ) : (
                      <Empty>Performance results not built. Run make gate5-performance.</Empty>
                    )}
                    <p className="mt-2 text-[11px] text-muted-foreground">Cloud costs: none measured yet. AWS deployment (Gate 9) has not been run, so no cost figure is shown.</p>
                  </div>
                </div>
              </div>
            );
          }}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function Reader({ slug }: { slug: string }) {
  const q = useQuery({ queryKey: ["report", slug], queryFn: () => request<CatalogEntry & { markdown: string; source: Source }>(`/api/v1/reports/${slug}`) });
  return (
    <QueryState q={q}>
      {(r) => (
        <Card>
          <CardHeader>
            <CardDescription>
              <code>{r.source.path}</code> · SHA-256 {short(r.source.sha256, 16)}
            </CardDescription>
          </CardHeader>
          <CardContent className="prose-report max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ img: () => null }}>{r.markdown}</ReactMarkdown>
          </CardContent>
        </Card>
      )}
    </QueryState>
  );
}

export function ExperimentReports() {
  const [params, setParams] = useSearchParams();
  const slug = params.get("report");
  const catalog = useQuery({ queryKey: ["reports"], queryFn: () => request<{ items: CatalogEntry[] }>("/api/v1/reports") });
  return (
    <Page title="Experiment Reports" description="Actual results as committed: detection benchmarks, aerial association, decision economics, and the D1 diagnosis. Nothing is recomputed or reworded here.">
      <D1Summary />
      <Detection />
      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <Card>
          <CardHeader><CardTitle>Reports</CardTitle></CardHeader>
          <CardContent>
            <QueryState q={catalog}>
              {(c) => (
                <ul className="space-y-1">
                  {c.items.map((r) => (
                    <li key={r.slug}>
                      <button
                        disabled={!r.available}
                        onClick={() => setParams({ report: r.slug })}
                        aria-current={slug === r.slug ? "true" : undefined}
                        className={cn("w-full rounded px-2 py-1.5 text-left text-xs hover:bg-accent disabled:opacity-50", slug === r.slug && "bg-accent")}
                      >
                        <div className="flex items-center gap-1.5"><Badge variant="outline">{r.gate}</Badge><Badge variant={(OUTCOME[r.outcome] ?? OUTCOME.RECORDED).variant}>{(OUTCOME[r.outcome] ?? OUTCOME.RECORDED).text}</Badge></div>
                        <div className="mt-0.5 font-medium">{r.title}</div>
                        {!r.available && <div className="text-muted-foreground">not built</div>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </QueryState>
          </CardContent>
        </Card>
        {slug ? <Reader slug={slug} /> : <Empty>Choose a report to read it in full.</Empty>}
      </div>
    </Page>
  );
}
