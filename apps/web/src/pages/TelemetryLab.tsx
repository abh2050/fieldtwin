import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { EChart } from "@/components/EChart";
import { useMe } from "@/components/Layout";
import { Page } from "@/components/Page";
import { ErrorState, QueryState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { query, request, type Paged } from "@/lib/api";
import { interval, num, pct, when } from "@/lib/format";
import type { Alarm, Scenario } from "@/lib/types";

type Tag = { tag: string; unit_id: string; value_count: number; null_count: number; asset_id: string | null; physical_quantity: string | null };
type Point = { offset_s: number; simulated_time: string; value: number | null; unit: string; quality: string; sensor_status: string; equipment_state: string };
type Series = { tag: string; points: Point[]; fault_onset_offset_s: number | null; source: { path: string; config_sha256: string } };
type MethodRow = { method: string; event_recall: number; event_recall_interval: [number, number] | null; chance_event_recall: number; event_skill: number; false_alarms_per_hour: number; precision: number };
type Evaluations = { track: string; selected_method: string; selection_reason: string; held_out: { pooled: MethodRow[]; source: { path: string } }; in_regime: { methods: MethodRow[] } };

function ReplayControls({ scenario, runId }: { scenario: Scenario; runId: string }) {
  const me = useMe();
  const client = useQueryClient();
  const action = useMutation({
    mutationFn: (verb: "replay" | "pause" | "reset") =>
      request(`/api/v1/scenarios/${encodeURIComponent(scenario.scenario_id)}/${verb}`, {
        method: "POST",
        body: verb === "replay" ? { scenario_run_id: runId, speed: 600 } : undefined,
      }),
    onSettled: () => client.invalidateQueries({ queryKey: ["scenarios"] }),
  });
  const canAct = me.data && me.data.role !== "VIEWER";
  const r = scenario.replay?.scenario_run_id === runId ? scenario.replay : null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={!canAct || action.isPending || r?.state === "PLAYING"} onClick={() => action.mutate("replay")}>
          <Play className="h-3.5 w-3.5" aria-hidden /> Replay
        </Button>
        <Button size="sm" variant="outline" disabled={!canAct || action.isPending || r?.state !== "PLAYING"} onClick={() => action.mutate("pause")}>
          <Pause className="h-3.5 w-3.5" aria-hidden /> Pause
        </Button>
        <Button size="sm" variant="outline" disabled={!canAct || action.isPending || !scenario.replay} onClick={() => action.mutate("reset")}>
          <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Reset
        </Button>
        <span className="text-xs text-muted-foreground" aria-live="polite">
          {r
            ? `${r.state.toLowerCase()} at ${num(r.position_s / 3600, 1)} h of ${num(r.duration_s / 3600, 1)} h (${r.speed}× speed, last changed by ${r.updated_by})`
            : scenario.replay
              ? `replaying another run (${scenario.replay.scenario_run_id})`
              : "not replaying: the full stored series is shown"}
        </span>
      </div>
      {!canAct && (
        <p className="text-[11px] text-muted-foreground">
          Replay control needs an operator or supervisor token. Replay reads the stored run; it never simulates new data.
        </p>
      )}
      {action.isError && <ErrorState error={action.error} />}
    </div>
  );
}

function Chart({ series, alarms, position, showOnset }: { series: Series; alarms: Alarm[]; position: number | null; showOnset: boolean }) {
  const option = useMemo(() => {
    const shown = position === null ? series.points : series.points.filter((p) => p.offset_s <= position);
    const start = series.points[0] ? new Date(series.points[0].simulated_time).getTime() : 0;
    const lines: Record<string, unknown>[] = alarms.map((a) => ({
      xAxis: a.started_at,
      name: `alarm ${a.alarm_id}`,
      lineStyle: { color: "#dc2626", type: "solid" },
      label: { formatter: "alarm", color: "#dc2626" },
    }));
    if (showOnset && series.fault_onset_offset_s !== null)
      lines.push({
        xAxis: new Date(start + series.fault_onset_offset_s * 1000).toISOString(),
        name: "scenario fault onset (truth)",
        lineStyle: { color: "#7c3aed", type: "dashed" },
        label: { formatter: "fault onset (truth)", color: "#7c3aed" },
      });
    return {
      grid: { left: 80, right: 20, top: 30, bottom: 60 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "time" },
      yAxis: { type: "value", name: series.points[0]?.unit ?? "", scale: true },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 10 }],
      series: [
        {
          type: "line",
          name: series.tag,
          showSymbol: false,
          connectNulls: false,
          data: shown.map((p) => [p.simulated_time, p.value]),
          lineStyle: { width: 1.2, color: "#3b6ea5" },
          markLine: { symbol: "none", data: lines },
        },
      ],
    };
  }, [series, alarms, position, showOnset]);
  const missing = series.points.filter((p) => p.value === null).length;
  const shownCount = position === null ? series.points.length : series.points.filter((p) => p.offset_s <= position).length;
  return (
    <>
      <EChart option={option as never} height={360} label={`Stored synthetic series ${series.tag}, with detector alarms marked`} />
      <p className="text-[11px] text-muted-foreground">
        SYNTHETIC. Times in UTC on the scenario clock.{" "}
        {position === null
          ? `${series.points.length} stored samples`
          : `Replay shows ${shownCount} of ${series.points.length} stored samples, up to the replay position`}{" "}
        from <code>{series.source.path}</code>
        {missing > 0 && `; ${missing} missing (gaps are drawn as gaps, not filled)`}. Red lines are detector alarms on this run.
      </p>
    </>
  );
}

export function TelemetryLab() {
  const [params, setParams] = useSearchParams();
  const [showOnset, setShowOnset] = useState(false);
  const scenarios = useQuery({
    queryKey: ["scenarios"],
    queryFn: () => request<{ items: Scenario[] }>("/api/v1/scenarios"),
    refetchInterval: (q) => (q.state.data?.items.some((s) => s.replay?.state === "PLAYING") ? 2000 : false),
  });
  const runs = (scenarios.data?.items ?? []).flatMap((s) => s.runs.map((r) => ({ ...r, scenario: s })));
  const networkRuns = runs.filter((r) => r.output_uri.includes("aether_field/"));
  const runId = params.get("run") ?? networkRuns.find((r) => r.case_name === "fault")?.scenario_run_id ?? networkRuns[0]?.scenario_run_id ?? "";
  const run = runs.find((r) => r.scenario_run_id === runId);
  const tags = useQuery({
    queryKey: ["tags", runId],
    enabled: !!run,
    queryFn: () => request<{ items: Tag[] }>(`/api/v1/scenarios/${encodeURIComponent(run!.scenario_id)}/runs/${encodeURIComponent(runId)}/tags`),
  });
  const tag = params.get("tag") ?? tags.data?.items[0]?.tag ?? "";
  const series = useQuery({
    queryKey: ["series", runId, tag],
    enabled: !!run && !!tag,
    queryFn: () => request<Series>(`/api/v1/scenarios/${encodeURIComponent(run!.scenario_id)}/runs/${encodeURIComponent(runId)}/telemetry${query({ tag })}`),
  });
  const alarms = useQuery({
    queryKey: ["alarms", run?.scenario_id],
    enabled: !!run,
    queryFn: () => request<Paged<Alarm>>(`/api/v1/anomalies${query({ scenario_id: run!.scenario_id, limit: 500 })}`),
  });
  const evals = useQuery({ queryKey: ["evaluations"], queryFn: () => request<Evaluations>("/api/v1/model-evaluations") });
  const replay = run?.scenario.replay?.scenario_run_id === runId ? run?.scenario.replay : null;
  const position = replay && (replay.state === "PLAYING" || replay.state === "PAUSED") ? replay.position_s : null;
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    next.set(k, v);
    if (k === "run") next.delete("tag");
    setParams(next);
  };
  const runAlarms = (alarms.data?.items ?? []).filter((a) => a.scenario_run_id === runId);

  return (
    <Page title="Telemetry Lab" description="Stored synthetic sensor series from the field simulator, with replay, detector alarms overlaid, and the recorded detection evaluation.">
      <Card>
        <CardHeader>
          <CardTitle>Series</CardTitle>
          <CardDescription>Only operator-visible sensor readings are served. Simulator truth stays in separate files and is never sent to this screen.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <QueryState q={scenarios} isEmpty={(d) => d.items.length === 0} empty="No scenarios loaded. Run make field.">
            {() => (
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label htmlFor="run">Scenario run</Label>
                  <Select id="run" value={runId} onChange={(e) => set("run", e.target.value)} className="w-80">
                    {runs.map((r) => (
                      <option key={r.scenario_run_id} value={r.scenario_run_id}>
                        {r.scenario_run_id}
                        {r.output_uri.includes("aether_field/") ? "" : " (Gate 3, not served)"}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="tag">Sensor</Label>
                  <Select id="tag" value={tag} onChange={(e) => set("tag", e.target.value)} className="w-56" disabled={!tags.data}>
                    {(tags.data?.items ?? []).map((t) => (
                      <option key={t.tag} value={t.tag}>
                        {t.tag} ({t.unit_id}){t.null_count ? ` · ${t.null_count} missing` : ""}
                      </option>
                    ))}
                  </Select>
                </div>
                <label className="flex items-center gap-1.5 text-xs">
                  <input type="checkbox" checked={showOnset} onChange={(e) => setShowOnset(e.target.checked)} />
                  Show scenario truth: fault onset
                </label>
              </div>
            )}
          </QueryState>
          {run && <ReplayControls scenario={run.scenario} runId={runId} />}
          {run && (
            <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
              <Badge variant="warning">SYNTHETIC</Badge>
              <span>{run.scenario.scenario_name}</span>·<span>seed {run.random_seed}</span>·<span>{run.sample_count} samples every {run.sampling_interval_s} s</span>·
              <span>simulator {run.simulator_name} v{run.simulator_version}</span>
            </div>
          )}
          {run && tag && (
            <QueryState q={series} label="Loading stored series">
              {(s) => <Chart series={s} alarms={runAlarms} position={position} showOnset={showOnset} />}
            </QueryState>
          )}
          {runAlarms.length > 0 && (
            <Table>
              <THead><TR><TH>Alarm</TH><TH>Started</TH><TH>Score / threshold</TH><TH>Model</TH><TH>Recommendation</TH></TR></THead>
              <TBody>
                {runAlarms.map((a) => (
                  <TR key={a.alarm_id}>
                    <TD className="font-mono">{a.alarm_id}</TD>
                    <TD>{when(a.started_at)}</TD>
                    <TD className="tabular-nums">{num(a.score, 2)} / {num(a.threshold, 2)}</TD>
                    <TD>{a.model_id} v{a.model_version}</TD>
                    <TD>{a.recommendation_id ? <Link className="text-primary underline" to="/decisions">{a.action?.replace(/_/g, " ").toLowerCase()}</Link> : "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Detection evaluation (Gate 5, recorded)</CardTitle>
          <CardDescription>Held-out regimes pooled. A detector score is not a failure probability. Intervals are bootstrap 95%.</CardDescription>
        </CardHeader>
        <CardContent>
          <QueryState q={evals}>
            {(e) => (
              <>
                <Table>
                  <THead><TR><TH>Method</TH><TH>Event recall</TH><TH>95% interval</TH><TH>By chance</TH><TH>Event skill</TH><TH>False alarms / h</TH></TR></THead>
                  <TBody>
                    {e.held_out.pooled.map((m) => (
                      <TR key={m.method} data-selected={m.method === e.selected_method}>
                        <TD>{m.method}{m.method === e.selected_method && <Badge className="ml-1">selected in-regime</Badge>}</TD>
                        <TD className="tabular-nums">{pct(m.event_recall)}</TD>
                        <TD className="tabular-nums">{interval(m.event_recall_interval)}</TD>
                        <TD className="tabular-nums">{pct(m.chance_event_recall)}</TD>
                        <TD className="tabular-nums">{num(m.event_skill, 2)}</TD>
                        <TD className="tabular-nums">{num(m.false_alarms_per_hour, 4)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
                <p className="mt-2 text-[11px] text-muted-foreground">
                  {e.track}. Selection: {e.selection_reason} Source <code>{e.held_out.source.path}</code>.
                </p>
              </>
            )}
          </QueryState>
        </CardContent>
      </Card>
    </Page>
  );
}
