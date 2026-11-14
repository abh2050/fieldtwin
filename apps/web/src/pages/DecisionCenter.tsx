import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Band, Provenance, Status } from "@/components/badges";
import { useMe } from "@/components/Layout";
import { Page } from "@/components/Page";
import { ErrorState, QueryState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { newIdempotencyKey, query, request, type Paged } from "@/lib/api";
import { when } from "@/lib/format";
import type { Recommendation, WorkOrder } from "@/lib/types";

const DISPATCH = new Set(["FIELD_INSPECTION", "CHECK_INSTRUMENTATION"]);

function OpenWorkOrder({ rec }: { rec: Recommendation }) {
  const me = useMe();
  const client = useQueryClient();
  // One key per recommendation on this screen, so a retried click can't open two orders.
  const [key] = useState(newIdempotencyKey);
  const create = useMutation({
    mutationFn: () => request<WorkOrder>("/api/v1/work-orders", { method: "POST", body: { recommendation_id: rec.recommendation_id }, idempotencyKey: key }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["recommendations"] });
      client.invalidateQueries({ queryKey: ["work-orders"] });
      client.invalidateQueries({ queryKey: ["overview"] });
    },
  });
  if (rec.work_order_id)
    return (
      <span className="flex items-center gap-2 text-xs">
        <Link className="text-primary underline" to={`/maintenance?wo=${rec.work_order_id}`}>{rec.work_order_id}</Link>
        {rec.work_order_status && <Status value={rec.work_order_status} />}
      </span>
    );
  if (!DISPATCH.has(rec.action)) return <span className="text-xs text-muted-foreground">No dispatch recommended.</span>;
  const allowed = me.data && me.data.role !== "VIEWER";
  return (
    <div className="space-y-1">
      <Button size="sm" disabled={!allowed || create.isPending} onClick={() => create.mutate()}>
        Open work order
      </Button>
      {!allowed && <p className="text-[11px] text-muted-foreground">Needs an operator or supervisor token.</p>}
      {create.isError && <ErrorState error={create.error} />}
    </div>
  );
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const total = rec.terms.reduce((s, t) => s + t.points, 0);
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex flex-wrap items-center gap-2">
            <Band value={rec.priority_band} /> {rec.action.replace(/_/g, " ").toLowerCase()}
            <span className="font-normal text-muted-foreground">score {rec.priority_score}</span>
            <Provenance value={rec.provenance_class} />
          </CardTitle>
          <OpenWorkOrder rec={rec} />
        </div>
        <CardDescription>
          {rec.scenario_id} · alarm <span className="font-mono">{rec.alarm_id}</span> · decided {when(rec.decided_at)}
          {rec.respond_within_h ? ` · respond within ${rec.respond_within_h} h` : ""} · rules v{rec.rules_version}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-semibold">Why: the rule engine's explanation</h3>
          <ul className="list-disc space-y-1 pl-5 text-xs">{rec.explanation.map((e, i) => <li key={i}>{e}</li>)}</ul>
          <div className="mt-2 text-xs">
            <span className="text-muted-foreground">Candidates, most likely first: </span>
            {rec.candidate_assets.length ? rec.candidate_assets.map((a, i) => (
              <Link key={a} to={`/assets/${a}`} className="mr-1 text-primary underline">{i === 0 ? <strong>{a}</strong> : a}</Link>
            )) : "none"}
            {rec.suppressed_assets.length > 0 && <span className="text-muted-foreground"> · suppressed: {rec.suppressed_assets.join(", ")}</span>}
          </div>
        </div>
        <div>
          <h3 className="mb-1 text-xs font-semibold">Score: every point is a named term</h3>
          <Table>
            <THead><TR><TH>Term</TH><TH>Input</TH><TH className="text-right">Points</TH></TR></THead>
            <TBody>
              {rec.terms.map((t) => (
                <TR key={t.name}><TD title={t.rule}>{t.name.replace(/_/g, " ")}</TD><TD className="font-mono">{t.input}</TD><TD className="text-right tabular-nums">{t.points}</TD></TR>
              ))}
              <TR><TD className="font-semibold">Total</TD><TD /><TD className="text-right font-semibold tabular-nums">{total}</TD></TR>
            </TBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

export function DecisionCenter() {
  const [action, setAction] = useState("");
  const q = useQuery({
    queryKey: ["recommendations", action],
    queryFn: () => request<Paged<Recommendation>>(`/api/v1/recommendations${query({ action, limit: 200 })}`),
  });
  return (
    <Page
      title="Decision Center"
      description="Recommendations from the transparent rule engine, ranked by priority. Each comes from a detector alarm on a simulated run, and every score point is a stored term."
      actions={
        <div className="space-y-1">
          <Label htmlFor="action">Action</Label>
          <Select id="action" value={action} onChange={(e) => setAction(e.target.value)} className="w-56">
            <option value="">All actions</option>
            <option value="FIELD_INSPECTION">Field inspection</option>
            <option value="CHECK_INSTRUMENTATION">Check instrumentation</option>
            <option value="NO_ACTION_PLANNED_OPERATION">No action: planned operation</option>
            <option value="NEEDS_EVIDENCE">Needs evidence</option>
          </Select>
        </div>
      }
    >
      <p className="text-xs text-muted-foreground">
        <Badge variant="warning" className="mr-1">caution</Badge>
        The detector behind these alarms caught under half of held-out events, and in the economic model alarm-driven dispatch cost more than fixed rounds. See Experiment Reports.
      </p>
      <QueryState q={q} isEmpty={(p) => p.total === 0} empty="No recommendations. Run make gate7 and make app-db.">
        {(p) => <div className="space-y-3">{p.items.map((r) => <RecommendationCard key={r.recommendation_id} rec={r} />)}</div>}
      </QueryState>
    </Page>
  );
}
