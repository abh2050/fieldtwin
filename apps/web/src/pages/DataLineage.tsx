import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Provenance } from "@/components/badges";
import { KV, Page, Pager } from "@/components/Page";
import { Empty, QueryState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { query, request, type Paged } from "@/lib/api";
import { num, short, when } from "@/lib/format";
import type { Scenario } from "@/lib/types";

type DataSource = { source_system_id: string; provider: string; source_url: string; source_version: string; license: string; usage_constraints: string; is_project_generated: boolean; retrieval_timestamp: string | null; batches: number; observations: number };
type Batch = { batch_id: string; source_system_id: string; source_version: string; ingestion_timestamp: string; original_checksum: string; source_record_count: number; accepted_count: number; rejected_count: number; processing_status: string; manifest_uri: string; files: number };
type Quality = Paged<{ exception_id: number; exception_type: string; severity: string; source_system_id: string; dataset: string; source_record_key: string; field_name: string; rule_id: string; disposition: string; status: string; decision_rationale: string | null; detected_at: string }> & {
  summary: { exception_type: string; severity: string; status: string; source_system_id: string; exceptions: number }[];
};

function Sources() {
  const q = useQuery({ queryKey: ["sources"], queryFn: () => request<{ items: DataSource[] }>("/api/v1/data-sources") });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Source systems</CardTitle>
        <CardDescription>Real public sources keep their licence and usage constraints. Project-generated sources are synthetic.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState q={q} isEmpty={(d) => d.items.length === 0} empty="No sources. Run make db-seed.">
          {(d) => (
            <Table>
              <THead><TR><TH>Source</TH><TH>Kind</TH><TH>Version</TH><TH>Licence</TH><TH>Usage constraints</TH><TH className="text-right">Batches</TH><TH className="text-right">Observations</TH></TR></THead>
              <TBody>
                {d.items.map((s) => (
                  <TR key={s.source_system_id}>
                    <TD><div className="font-medium">{s.source_system_id}</div><a className="text-[11px] text-primary underline" href={s.source_url} target="_blank" rel="noreferrer">{s.provider}</a></TD>
                    <TD>{s.is_project_generated ? <Badge variant="warning">project-generated</Badge> : <Badge variant="success">real public</Badge>}</TD>
                    <TD>{s.source_version}</TD>
                    <TD className="max-w-xs">{s.license}</TD>
                    <TD className="max-w-sm">{s.usage_constraints}</TD>
                    <TD className="text-right tabular-nums">{num(s.batches)}</TD>
                    <TD className="text-right tabular-nums">{num(s.observations)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function Ingestion() {
  const [offset, setOffset] = useState(0);
  const q = useQuery({ queryKey: ["batches", offset], queryFn: () => request<Paged<Batch>>(`/api/v1/ingestion-runs${query({ limit: 20, offset })}`) });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ingestion runs</CardTitle>
        <CardDescription>Immutable raw batches, each with a manifest and checksum.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <QueryState q={q} isEmpty={(p) => p.total === 0} empty="No batches loaded. Run make acquire and make db-load.">
          {(p) => (
            <>
              <Table>
                <THead><TR><TH>Batch</TH><TH>Source</TH><TH>Ingested</TH><TH className="text-right">Records</TH><TH className="text-right">Accepted</TH><TH className="text-right">Rejected</TH><TH className="text-right">Files</TH><TH>Status</TH><TH>Checksum</TH></TR></THead>
                <TBody>
                  {p.items.map((b) => (
                    <TR key={b.batch_id}>
                      <TD className="font-mono">{b.batch_id}</TD>
                      <TD>{b.source_system_id}</TD>
                      <TD>{when(b.ingestion_timestamp)}</TD>
                      <TD className="text-right tabular-nums">{num(b.source_record_count)}</TD>
                      <TD className="text-right tabular-nums">{num(b.accepted_count)}</TD>
                      <TD className="text-right tabular-nums">{num(b.rejected_count)}</TD>
                      <TD className="text-right tabular-nums">{num(b.files)}</TD>
                      <TD>{b.processing_status}</TD>
                      <TD className="font-mono" title={b.original_checksum}>{short(b.original_checksum)}</TD>
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
  );
}

function DataQuality() {
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ["quality", status, severity, offset],
    queryFn: () => request<Quality>(`/api/v1/data-quality${query({ status, severity, limit: 20, offset })}`),
  });
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <CardTitle>Data quality</CardTitle>
            <CardDescription>Quarantined and flagged records, with the rule and decision for each.</CardDescription>
          </div>
          <div className="flex gap-2">
            <div className="space-y-1"><Label htmlFor="dq-status">Status</Label>
              <Select id="dq-status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className="w-32"><option value="">All</option><option>OPEN</option><option>ACCEPTED</option></Select></div>
            <div className="space-y-1"><Label htmlFor="dq-sev">Severity</Label>
              <Select id="dq-sev" value={severity} onChange={(e) => { setSeverity(e.target.value); setOffset(0); }} className="w-32"><option value="">All</option><option>ERROR</option><option>WARNING</option></Select></div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <QueryState q={q} isEmpty={(p) => p.total === 0} empty="No exceptions match these filters.">
          {(p) => (
            <>
              <Table>
                <THead><TR><TH>Exception type</TH><TH>Source</TH><TH>Severity</TH><TH>Status</TH><TH className="text-right">Count</TH></TR></THead>
                <TBody>{p.summary.map((s, i) => <TR key={i}><TD>{s.exception_type}</TD><TD>{s.source_system_id}</TD><TD>{s.severity}</TD><TD>{s.status}</TD><TD className="text-right tabular-nums">{num(s.exceptions)}</TD></TR>)}</TBody>
              </Table>
              <Table>
                <THead><TR><TH>#</TH><TH>Type</TH><TH>Record</TH><TH>Field</TH><TH>Rule</TH><TH>Disposition</TH><TH>Rationale</TH></TR></THead>
                <TBody>
                  {p.items.map((x) => (
                    <TR key={x.exception_id}><TD>{x.exception_id}</TD><TD>{x.exception_type}</TD><TD className="font-mono">{x.dataset}:{x.source_record_key}</TD><TD>{x.field_name}</TD><TD>{x.rule_id}</TD><TD>{x.disposition}</TD><TD className="max-w-sm">{x.decision_rationale ?? "—"}</TD></TR>
                  ))}
                </TBody>
              </Table>
              <Pager total={p.total} limit={p.limit} offset={p.offset} onChange={setOffset} />
            </>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function Scenarios() {
  const q = useQuery({ queryKey: ["scenarios"], queryFn: () => request<{ items: Scenario[] }>("/api/v1/scenarios") });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Scenario mappings</CardTitle>
        <CardDescription>Every simulated run, with its seed, parameter hash, and output, so it can be rebuilt bit for bit.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState q={q} isEmpty={(d) => d.items.length === 0} empty="No scenarios. Run make field.">
          {(d) => (
            <Table>
              <THead><TR><TH>Run</TH><TH>Case</TH><TH>Target / affected</TH><TH>Seed</TH><TH>Parameters</TH><TH>Output hash</TH><TH>Output</TH></TR></THead>
              <TBody>
                {d.items.flatMap((s) => s.runs).map((r) => (
                  <TR key={r.scenario_run_id}>
                    <TD className="font-mono">{r.scenario_run_id} <Provenance value="SYNTHETIC" /></TD>
                    <TD>{r.case_name}</TD>
                    <TD>{r.target_asset_id ?? "—"} / {r.affected_asset_id ?? "—"}</TD>
                    <TD className="tabular-nums">{r.random_seed}</TD>
                    <TD className="font-mono" title={r.config_sha256}>{short(r.config_sha256)}</TD>
                    <TD className="font-mono" title={r.output_sha256}>{short(r.output_sha256)}</TD>
                    <TD className="font-mono text-[11px]">{r.output_uri}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function Value({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <>—</>;
  if (typeof v === "object") return <pre className="whitespace-pre-wrap text-[11px]">{JSON.stringify(v, null, 1)}</pre>;
  return <>{String(v)}</>;
}

function Lineage() {
  const [params, setParams] = useSearchParams();
  const record = params.get("record") ?? "";
  const [draft, setDraft] = useState(record);
  const q = useQuery({
    queryKey: ["lineage", record],
    enabled: !!record,
    queryFn: () => request<{ kind: string; lineage: Record<string, unknown> }>(`/api/v1/lineage/${encodeURIComponent(record)}`),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams(draft.trim() ? { record: draft.trim() } : {});
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>Raw-to-curated lineage</CardTitle>
        <CardDescription>Trace a record to its raw file, batch, checksum, and transformation. Use kind:id, for example observation:1, production:1, or telemetry_event:ID.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form onSubmit={submit} className="flex gap-2">
          <label htmlFor="record" className="sr-only">Record</label>
          <Input id="record" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="observation:1" className="max-w-xs" />
          <Button type="submit" size="sm">Trace</Button>
        </form>
        {!record ? (
          <Empty>Enter a record, or follow a "trace" link from the Asset Explorer.</Empty>
        ) : (
          <QueryState q={q}>
            {(d) => (
              <div className="space-y-3">
                {Object.entries(d.lineage).map(([k, v]) =>
                  v && typeof v === "object" && !Array.isArray(v) ? (
                    <div key={k}>
                      <h3 className="mb-1 text-xs font-semibold">{k.replace(/_/g, " ")}</h3>
                      <KV rows={Object.entries(v as Record<string, unknown>).map(([a, b]) => [a, <Value key={a} v={b} />])} />
                    </div>
                  ) : null,
                )}
                {Object.values(d.lineage).every((v) => typeof v !== "object" || v === null) && (
                  <KV rows={Object.entries(d.lineage).map(([a, b]) => [a, <Value key={a} v={b} />])} />
                )}
              </div>
            )}
          </QueryState>
        )}
      </CardContent>
    </Card>
  );
}

export function DataLineage() {
  return (
    <Page title="Data Lineage" description="Source inventory, ingestion runs, data quality, scenario mappings, and the path from any record back to its raw file.">
      <Lineage />
      <Sources />
      <Ingestion />
      <DataQuality />
      <Scenarios />
    </Page>
  );
}
