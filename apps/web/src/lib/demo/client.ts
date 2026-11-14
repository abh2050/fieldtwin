import { ApiError, getToken, type RequestOptions } from "../api";
import type { Alarm, Asset, AssetDetail, Me, Recommendation, Replay, Scenario, Transition, WorkOrder } from "../types";

export type DemoSnapshot = {
  schema_version: number;
  disclosure: string;
  assets: Asset[];
  details: Record<string, AssetDetail>;
  relationships: Record<string, unknown>;
  observations: Record<string, Record<string, unknown>[]>;
  lineage: Record<string, unknown>;
  scenarios: Scenario[];
  recommendations: Recommendation[];
  alarms: Alarm[];
  inspection_requests: Record<string, unknown>[];
  data_sources: Record<string, unknown>[];
  ingestion_runs: Record<string, unknown>[];
  quality: { items: Record<string, unknown>[]; summary: Record<string, unknown>[] };
  reads: Record<string, unknown>;
  telemetry: Record<string, { files: Record<string, string>; tags: { items: Record<string, unknown>[]; total: number } }>;
};
type FileEntry = { sha256: string; bytes: number; encoding: "gzip" | "json" };
type Manifest = { schema_version: number; files: Record<string, FileEntry> };
type PackedRun = { columns: string[]; series: Record<string, { rows: unknown[][]; [key: string]: unknown }> };
type Cursor = Replay & { anchored_at_ms: number };
type SessionState = {
  version: 1;
  orders: WorkOrder[];
  replays: Record<string, Cursor>;
  idempotency: Record<string, { signature: string; response: unknown }>;
};
const emptyState = (): SessionState => ({ version: 1, orders: [], replays: {}, idempotency: {} });
const fail = (status: number, code: string, message: string): never => { throw new ApiError(status, code, message, null, null); };
const roleNames = ["VIEWER", "OPERATOR", "MAINTENANCE_SUPERVISOR"] as const;

function actor(): Me {
  const role = getToken()?.replace(/^demo:/, "");
  if (!roleNames.includes(role as Me["role"])) return fail(401, "DEMO_ROLE_REQUIRED", "Select a browser demo role.");
  return { actor_id: "browser-demo", role: role as Me["role"] };
}

async function fetchBytes(path: string): Promise<Uint8Array> {
  let response: Response;
  try { response = await fetch(path); }
  catch { return fail(0, "DEMO_BUNDLE_UNREACHABLE", "The simulation bundle could not be loaded. Check the deployment and retry."); }
  if (!response.ok) return fail(response.status, "DEMO_BUNDLE_MISSING", `Required demo file is missing: ${path}. Rebuild with npm run build:demo.`);
  return new Uint8Array(await response.arrayBuffer());
}

async function loadFile(name: string, manifest: Manifest): Promise<unknown> {
  if (!/^[a-z0-9_-]+\.(json|bin)$/.test(name) || !manifest.files[name])
    return fail(422, "INVALID_DEMO_FILE", "The simulation manifest references an invalid file.");
  const entry = manifest.files[name];
  const bytes = await fetchBytes(`/demo/${name}`);
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map((v) => v.toString(16).padStart(2, "0")).join("");
  if (hash !== entry.sha256 || bytes.byteLength !== entry.bytes)
    return fail(409, "DEMO_INTEGRITY_ERROR", `Simulation file ${name} does not match its manifest. Reload after deployment completes.`);
  let text: string;
  if (entry.encoding === "gzip") {
    if (typeof DecompressionStream === "undefined") return fail(422, "BROWSER_UNSUPPORTED", "This demo needs a browser with gzip stream support. Use a current browser or run the local API.");
    text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
  } else { text = new TextDecoder().decode(bytes); }
  try { return JSON.parse(text); }
  catch { return fail(422, "INVALID_DEMO_BUNDLE", `Simulation file ${name} is not valid JSON.`); }
}

// Files are loaded once per tab. A rejected load is evicted so retry never fabricates a substitute.
let loaded: Promise<DemoSession> | undefined;
async function loadSession(): Promise<DemoSession> {
  if (!loaded) loaded = (async () => {
    let manifest: Manifest;
    try { manifest = JSON.parse(new TextDecoder().decode(await fetchBytes("/demo/manifest.json"))); }
    catch (error) {
      if (error instanceof ApiError) throw error;
      return fail(422, "INVALID_DEMO_MANIFEST", "The static host returned an invalid simulation manifest. Check the demo build and routing.");
    }
    if (manifest.schema_version !== 1 || !manifest.files?.["snapshot.json"])
      return fail(422, "INVALID_DEMO_MANIFEST", "Unsupported simulation bundle version.");
    const snapshot = await loadFile("snapshot.json", manifest) as DemoSnapshot;
    if (snapshot.schema_version !== 1 || !Array.isArray(snapshot.assets) || !Array.isArray(snapshot.scenarios))
      return fail(422, "INVALID_DEMO_BUNDLE", "The simulation snapshot has an invalid schema.");
    const runs = new Map<string, Promise<PackedRun>>();
    const readRun = (id: string, tag: string) => {
      const ref = snapshot.telemetry[id];
      const filename = ref?.files[tag];
      if (!filename) return Promise.reject(new ApiError(404, "RUN_NOT_FOUND", "This run is not packaged in the browser demo.", null, null));
      let pending = runs.get(filename);
      if (!pending) {
        pending = loadFile(filename, manifest).then((value) => value as PackedRun).catch((error) => { runs.delete(filename); throw error; });
        runs.set(filename, pending);
      }
      return pending;
    };
    return new DemoSession(snapshot, sessionStorage, manifest.files["snapshot.json"].sha256, readRun);
  })().catch((error) => { loaded = undefined; throw error; });
  return loaded;
}

export class DemoSession {
  private state: SessionState = emptyState();
  private readonly key: string;
  constructor(
    readonly snapshot: DemoSnapshot,
    private readonly storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
    bundleId: string,
    private readonly readRun: (id: string, tag: string) => Promise<PackedRun>,
    private readonly now: () => number = Date.now,
  ) {
    this.key = `fieldtwin.demo.session.${bundleId}`;
    const stored = storage.getItem(this.key);
    if (!stored) this.state = emptyState();
    else {
      try {
        const parsed = JSON.parse(stored) as SessionState;
        if (parsed.version !== 1 || !Array.isArray(parsed.orders) || !parsed.replays || !parsed.idempotency ||
          parsed.orders.some((o) => !Array.isArray(o.transitions) || o.transitions.some((t) => !["SYSTEM", "SCRIPTED_DEMO"].includes(t.actor_kind))))
          throw new Error("Invalid session schema");
        this.state = parsed;
      } catch { return fail(422, "INVALID_DEMO_SESSION", "The browser demo session is invalid. Use Reset demo to clear it."); }
    }
  }
  reset() { this.storage.removeItem(this.key); this.state = emptyState(); }
  private cursor(scenario: Scenario): Cursor | null {
    const cursor = this.state.replays[scenario.scenario_id];
    if (!cursor) return null;
    const view = { ...cursor };
    if (view.state === "PLAYING") {
      view.position_s = Math.min(view.duration_s, cursor.position_s + Math.max(0, this.now() - cursor.anchored_at_ms) / 1000 * cursor.speed);
      if (view.position_s >= view.duration_s) view.state = "FINISHED";
    }
    return view;
  }
  async request(path: string, init: RequestOptions, who: Me): Promise<unknown> {
    if (!path.startsWith("/") || path.startsWith("//")) return fail(422, "INVALID_DEMO_PATH", "Use a local demo route.");
    const url = new URL(path, "https://browser-demo.invalid");
    const route = decodeURIComponent(url.pathname);
    const params = url.searchParams;
    const limit = Number(params.get("limit") ?? 25), offset = Number(params.get("offset") ?? 0);
    if (!Number.isInteger(limit) || limit < 1 || limit > 500 || !Number.isInteger(offset) || offset < 0)
      return fail(422, "INVALID_PAGE", "Use a page limit of 1–500 and a nonnegative offset.");
    const page = <T>(items: T[]) => ({ items: items.slice(offset, offset + limit), total: items.length, limit, offset });
    if (init.method === "POST") return this.write(route, init, who);
    if (route === "/health") return { status: "demo", checks: { database: "not_connected", writes_enabled: true }, disclosure: this.snapshot.disclosure };
    if (route === "/api/v1/me") return who;
    if (route === "/api/v1/scenarios") return { items: this.snapshot.scenarios.map((s) => ({ ...s, replay: this.cursor(s) })), total: this.snapshot.scenarios.length };
    if (route === "/api/v1/recommendations") return page(this.snapshot.recommendations
      .filter((r) => (!params.get("action") || r.action === params.get("action")) && (!params.get("scenario_id") || r.scenario_id === params.get("scenario_id")))
      .map((r) => { const order = this.state.orders.find((o) => o.recommendation_id === r.recommendation_id); return { ...r, work_order_id: order?.work_order_id ?? null, work_order_status: order?.status ?? null }; }));
    if (route === "/api/v1/work-orders") return { ...page(this.state.orders.filter((o) => !params.get("status") || o.status === params.get("status"))), note: "Browser demonstration work orders. Changes are session-only; demonstration actors are SCRIPTED_DEMO, not authenticated people." };
    if (route === "/api/v1/anomalies") return page(this.snapshot.alarms.filter((a) => !params.get("scenario_id") || a.scenario_id === params.get("scenario_id")));
    if (route === "/api/v1/assets") return page(this.snapshot.assets.filter((a) =>
      (!params.get("asset_type") || a.asset_type === params.get("asset_type")) &&
      (!params.get("parent_asset_id") || a.parent_asset_id === params.get("parent_asset_id")) &&
      (!params.get("q") || `${a.asset_id} ${a.asset_name}`.toLowerCase().includes(params.get("q")!.toLowerCase()))));
    const assetMatch = route.match(/^\/api\/v1\/assets\/([^/]+)(?:\/(relationships|observations))?$/);
    if (assetMatch) {
      const [, id, view] = assetMatch;
      const detail = this.snapshot.details[id];
      if (!detail) return fail(404, "ASSET_NOT_FOUND", "This asset is not packaged in the simulation.");
      if (view === "relationships") return this.snapshot.relationships[id];
      if (view === "observations") return page(this.snapshot.observations[id].filter((o) => !params.get("scenario_run_id") || o.scenario_run_id === params.get("scenario_run_id")));
      return { ...detail, work_orders: this.state.orders.filter((o) => o.asset_id === id).map((o) => ({ external_id: o.work_order_id, status: o.status, priority_band: o.priority_band, created_at: o.created_at })) };
    }
    const seriesMatch = route.match(/^\/api\/v1\/scenarios\/([^/]+)\/runs\/([^/]+)\/(tags|telemetry)$/);
    if (seriesMatch) {
      const [, scenarioId, runId, view] = seriesMatch;
      const scenario = this.snapshot.scenarios.find((s) => s.scenario_id === scenarioId);
      if (!scenario?.runs.some((r) => r.scenario_run_id === runId)) return fail(404, "RUN_NOT_FOUND", "This scenario run is not packaged.");
      if (view === "tags") return this.snapshot.telemetry[runId].tags;
      const tag = params.get("tag") ?? "";
      if (!this.snapshot.telemetry[runId].files[tag]) return fail(404, "TAG_NOT_FOUND", "This sensor series is not packaged.");
      const packed = await this.readRun(runId, tag);
      const series = packed.series[tag];
      if (!series) return fail(404, "TAG_NOT_FOUND", "This sensor series is not packaged.");
      const { rows, ...meta } = series;
      const until = params.has("until_offset_s") ? Number(params.get("until_offset_s")) : Infinity;
      if (Number.isNaN(until) || until < 0) return fail(422, "INVALID_OFFSET", "The replay offset must be nonnegative.");
      const points = rows.map((row) => Object.fromEntries(packed.columns.map((column, i) => [column, row[i]]))).filter((p) => Number(p.offset_s) <= until);
      return { ...meta, points };
    }
    if (route === "/api/v1/overview") {
      const base = this.snapshot.reads[route] as Record<string, unknown>;
      const backlog: Record<string, number> = {}, kinds: Record<string, number> = {};
      for (const order of this.state.orders) {
        backlog[order.status] = (backlog[order.status] ?? 0) + 1;
        for (const t of order.transitions.filter((t) => t.decision !== "CREATE")) kinds[t.actor_kind] = (kinds[t.actor_kind] ?? 0) + 1;
      }
      return { ...base, work_order_backlog: Object.entries(backlog).map(([status, n]) => ({ status, n })), decisions_by_actor_kind: Object.entries(kinds).map(([actor_kind, n]) => ({ actor_kind, n })) };
    }
    if (route === "/api/v1/data-sources") return { items: this.snapshot.data_sources, total: this.snapshot.data_sources.length };
    if (route === "/api/v1/ingestion-runs") return page(this.snapshot.ingestion_runs.filter((b) => !params.get("source_system_id") || b.source_system_id === params.get("source_system_id")));
    if (route === "/api/v1/data-quality") {
      const choose = (row: Record<string, unknown>) => ["status", "severity", "source_system_id"].every((k) => !params.get(k) || row[k] === params.get(k));
      return { ...page(this.snapshot.quality.items.filter(choose)), summary: this.snapshot.quality.summary.filter(choose) };
    }
    if (route.startsWith("/api/v1/lineage/")) {
      const record = route.slice("/api/v1/lineage/".length);
      return this.snapshot.lineage[record] ?? fail(404, "RECORD_NOT_PACKAGED", "Only the packaged synthetic observation lineage is available in this demo.");
    }
    if (route === "/api/v1/inspections") return {
      requests: { items: this.snapshot.inspection_requests, total: this.snapshot.inspection_requests.length, provenance_class: "SYNTHETIC" },
      evidence: { packaged: false, source: null, note: "Public aerial evidence is not packaged in the browser demo. Use the local API for licensed source records, imagery, and reviews. No evidence or reviews are generated in their place.", coverage_counts: {}, review_counts: [], ...page([]) },
    };
    if (Object.hasOwn(this.snapshot.reads, route)) return this.snapshot.reads[route];
    return fail(404, "DEMO_ROUTE_NOT_AVAILABLE", "This route is not available in the browser demonstration.");
  }
  private write(route: string, init: RequestOptions, who: Me): unknown {
    if (who.role === "VIEWER") return fail(403, "DEMO_ROLE_FORBIDDEN", "Select an operator or maintenance supervisor demo role to act.");
    const signature = JSON.stringify([route, init.body ?? null]);
    const key = init.idempotencyKey ? `${who.role}:${init.idempotencyKey}` : null;
    const previous = key ? this.state.idempotency[key] : null;
    if (previous) {
      if (previous.signature !== signature) return fail(422, "IDEMPOTENCY_CONFLICT", "This idempotency key belongs to a different demo request.");
      return previous.response;
    }
    const body = (init.body ?? {}) as Record<string, unknown>;
    const next = structuredClone(this.state);
    const recordedAt = new Date(this.now()).toISOString();
    let result: unknown;
    if (route === "/api/v1/work-orders") {
      const rec = this.snapshot.recommendations.find((r) => r.recommendation_id === body.recommendation_id);
      if (!rec) return fail(404, "RECOMMENDATION_NOT_FOUND", "No packaged recommendation has that ID.");
      if (!["FIELD_INSPECTION", "CHECK_INSTRUMENTATION"].includes(rec.action) || !rec.priority_band || !rec.candidate_assets[0]) return fail(409, "RECOMMENDATION_DOES_NOT_DISPATCH", "This recommendation does not open a work order.");
      if (next.orders.some((o) => o.recommendation_id === rec.recommendation_id)) return fail(409, "WORK_ORDER_EXISTS", "A session work order already exists for this recommendation.");
      const order: WorkOrder = { work_order_id: `DEMO-WO-${String(next.orders.length + 1).padStart(4, "0")}`, scenario_id: rec.scenario_id, asset_id: rec.candidate_assets[0], recommended_action: rec.action, priority: rec.priority_score, priority_band: rec.priority_band, status: "RECOMMENDED", created_at: rec.decided_at, recommendation_id: rec.recommendation_id, decided_by_kinds: [], transitions: [{ sequence: 0, decision: "CREATE", from_status: null, to_status: "RECOMMENDED", actor_id: "browser-demo-engine", actor_kind: "SYSTEM", actor_role: "SYSTEM", justification: `Requested by the ${who.role} browser demo role; session only.`, decided_at: rec.decided_at, recorded_at: recordedAt }] };
      next.orders.push(order); result = order;
    } else {
      const decision = route.match(/^\/api\/v1\/work-orders\/([^/]+)\/(approve|reject|request-evidence|complete)$/);
      const replay = route.match(/^\/api\/v1\/scenarios\/([^/]+)\/(replay|pause|reset)$/);
      if (decision) {
        const [, id, verb] = decision;
        const order = next.orders.find((o) => o.work_order_id === id);
        if (!order) return fail(404, "WORK_ORDER_NOT_FOUND", "No session work order has that ID.");
        if (verb !== "complete" && who.role !== "MAINTENANCE_SUPERVISOR") return fail(403, "SUPERVISOR_REQUIRED", "Approval, rejection, and evidence requests require the maintenance supervisor demo role.");
        if (typeof body.justification !== "string" || !body.justification.trim() || body.justification.length > 2000) return fail(422, "JUSTIFICATION_REQUIRED", "Record a justification of 1–2000 characters.");
        const transitions: Record<string, [string[], string, string]> = {
          approve: [["RECOMMENDED"], "APPROVED", "APPROVE"], reject: [["RECOMMENDED", "NEEDS_EVIDENCE"], "REJECTED", "REJECT"],
          "request-evidence": [["RECOMMENDED"], "NEEDS_EVIDENCE", "REQUEST_EVIDENCE"], complete: [["APPROVED"], "COMPLETED", "COMPLETE"],
        };
        const [allowed, target, label] = transitions[verb];
        if (!allowed.includes(order.status)) return fail(409, "INVALID_TRANSITION", `${label} is not allowed from ${order.status}.`);
        const event: Transition = { sequence: order.transitions.length, decision: label, from_status: order.status, to_status: target, actor_id: "browser-demo", actor_kind: "SCRIPTED_DEMO", actor_role: who.role, justification: body.justification.trim(), decided_at: order.transitions.at(-1)!.decided_at, recorded_at: recordedAt };
        order.status = target; order.transitions.push(event); order.decided_by_kinds = ["SCRIPTED_DEMO"]; result = order;
      } else if (replay) {
        const [, scenarioId, verb] = replay;
        const scenario = this.snapshot.scenarios.find((s) => s.scenario_id === scenarioId);
        if (!scenario) return fail(404, "SCENARIO_NOT_FOUND", "This scenario is not packaged.");
        const current = this.cursor(scenario);
        const run = scenario.runs.find((r) => r.scenario_run_id === (body.scenario_run_id ?? current?.scenario_run_id)) ?? (!body.scenario_run_id ? scenario.runs[0] : undefined);
        if (!run) return fail(404, "RUN_NOT_FOUND", "Select a run from this scenario.");
        if (verb === "pause" && current?.state !== "PLAYING") return fail(409, "REPLAY_NOT_PLAYING", "Start replay before pausing.");
        const speed = body.speed ?? current?.speed ?? 600;
        if (typeof speed !== "number" || !Number.isFinite(speed) || speed <= 0 || speed > 3600) return fail(422, "INVALID_REPLAY_SPEED", "Use a replay speed greater than zero and at most 3600.");
        const cursor: Cursor = { scenario_run_id: run.scenario_run_id, state: verb === "pause" ? "PAUSED" : verb === "reset" ? "STOPPED" : "PLAYING", position_s: verb === "reset" || current?.scenario_run_id !== run.scenario_run_id || current?.state === "FINISHED" ? 0 : current?.position_s ?? 0, duration_s: run.sample_count * run.sampling_interval_s, speed, updated_by: "browser-demo · SCRIPTED_DEMO", anchored_at_ms: this.now() };
        next.replays[scenarioId] = cursor; result = cursor;
      } else return fail(404, "DEMO_ACTION_NOT_AVAILABLE", "This action is not available in the browser demo.");
    }
    if (key) next.idempotency[key] = { signature, response: structuredClone(result) };
    this.storage.setItem(this.key, JSON.stringify(next));
    this.state = next;
    return result;
  }
}

export async function demoRequest<T>(path: string, init: RequestOptions = {}): Promise<T> {
  if (init.signal?.aborted) throw new DOMException("Aborted", "AbortError");
  const session = await loadSession();
  return structuredClone(await session.request(path, init, actor())) as T;
}

export async function resetDemoSession(): Promise<void> {
  // Clear even a corrupt stored session: the bundle load can then construct a fresh session.
  for (let i = sessionStorage.length - 1; i >= 0; i--) {
    const key = sessionStorage.key(i);
    if (key?.startsWith("fieldtwin.demo.session.")) sessionStorage.removeItem(key);
  }
  loaded = undefined;
}
