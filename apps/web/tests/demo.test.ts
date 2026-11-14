import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DemoSession, type DemoSnapshot } from "@/lib/demo/client";
import type { Me, Replay, WorkOrder } from "@/lib/types";

const base = resolve(process.cwd(), "demo-public/demo");
const snapshot: DemoSnapshot = JSON.parse(readFileSync(resolve(base, "snapshot.json"), "utf8"));
const op: Me = { actor_id: "browser-demo", role: "OPERATOR" };
const supervisor: Me = { ...op, role: "MAINTENANCE_SUPERVISOR" };
const viewer: Me = { ...op, role: "VIEWER" };
const recommendation = snapshot.recommendations.find((r) => r.action === "FIELD_INSPECTION")!;
const scenario = snapshot.scenarios[0];
const run = scenario.runs[0];
let now: number;
let demo: DemoSession;
const readRun = vi.fn(async (id: string, tag: string) => JSON.parse(gunzipSync(readFileSync(resolve(base, snapshot.telemetry[id].files[tag]))).toString()));
const create = (key = "create-key") => demo.request("/api/v1/work-orders", { method: "POST", body: { recommendation_id: recommendation.recommendation_id }, idempotencyKey: key }, op) as Promise<WorkOrder>;
const decide = (order: WorkOrder, verb: string, role = supervisor, justification = "Reviewed the alarm and candidate equipment.") => demo.request(`/api/v1/work-orders/${order.work_order_id}/${verb}`, { method: "POST", body: { justification } }, role) as Promise<WorkOrder>;

beforeEach(() => {
  sessionStorage.clear(); now = Date.parse("2026-11-14T22:00:00Z");
  demo = new DemoSession(snapshot, sessionStorage, "test-bundle", readRun, () => now);
  readRun.mockClear();
});

describe("browser simulation", () => {
  it("reports a demo rather than a healthy API/database", async () => {
    await expect(demo.request("/health", {}, op)).resolves.toMatchObject({ status: "demo", checks: { database: "not_connected" } });
  });
  it("loads six existing scenarios and no prior decisions", async () => {
    const scenarios = await demo.request("/api/v1/scenarios", {}, op) as { items: { replay: null }[] };
    expect(scenarios.items).toHaveLength(6);
    expect(scenarios.items.every((s) => s.replay === null)).toBe(true);
    await expect(demo.request("/api/v1/work-orders", {}, op)).resolves.toMatchObject({ total: 0 });
  });
  it("paginates assets and refuses unknown assets and routes", async () => {
    await expect(demo.request("/api/v1/assets?limit=5&offset=5", {}, op)).resolves.toMatchObject({ total: 47, items: snapshot.assets.slice(5, 10) });
    await expect(demo.request("/api/v1/assets/unknown", {}, op)).rejects.toMatchObject({ status: 404 });
    await expect(demo.request("/api/v1/missing", {}, op)).rejects.toMatchObject({ status: 404 });
    await expect(demo.request("/api/v1/assets?limit=0", {}, op)).rejects.toMatchObject({ status: 422 });
  });
  it("only reads a telemetry chunk when that run and tag are requested", async () => {
    const prefix = `/api/v1/scenarios/${scenario.scenario_id}/runs/${run.scenario_run_id}`;
    await demo.request(`${prefix}/tags`, {}, op);
    expect(readRun).not.toHaveBeenCalled();
    const tag = String(snapshot.telemetry[run.scenario_run_id].tags.items[0].tag);
    const series = await demo.request(`${prefix}/telemetry?tag=${tag}&until_offset_s=600`, {}, op) as { points: { offset_s: number; unit: string }[] };
    expect(readRun).toHaveBeenCalledWith(run.scenario_run_id, tag);
    expect(series.points.map((p) => p.offset_s)).toEqual([0, 300, 600]);
    await expect(demo.request(`${prefix}/telemetry?tag=unknown`, {}, op)).rejects.toMatchObject({ code: "TAG_NOT_FOUND" });
  });
  it("keeps acquisition failures visible when a telemetry chunk cannot load", async () => {
    const broken = new DemoSession(snapshot, sessionStorage, "broken", async () => { throw new Error("missing chunk"); });
    await expect(broken.request(`/api/v1/scenarios/${scenario.scenario_id}/runs/${run.scenario_run_id}/telemetry?tag=A-01.FT`, {}, op)).rejects.toThrow("missing chunk");
  });
  it("advances, pauses, resumes, finishes, and resets a stored replay", async () => {
    const prefix = `/api/v1/scenarios/${scenario.scenario_id}`;
    const get = async () => ((await demo.request("/api/v1/scenarios", {}, op)) as { items: { scenario_id: string; replay: Replay }[] }).items.find((s) => s.scenario_id === scenario.scenario_id)!.replay;
    await demo.request(`${prefix}/replay`, { method: "POST", body: { scenario_run_id: run.scenario_run_id, speed: 600 } }, op);
    now += 2000;
    expect((await get()).position_s).toBe(1200);
    await demo.request(`${prefix}/pause`, { method: "POST" }, op);
    now += 5000;
    expect((await get()).position_s).toBe(1200);
    await demo.request(`${prefix}/replay`, { method: "POST" }, op);
    now += 10_000_000;
    expect((await get()).state).toBe("FINISHED");
    await demo.request(`${prefix}/reset`, { method: "POST" }, op);
    expect(await get()).toMatchObject({ state: "STOPPED", position_s: 0 });
  });
  it("refuses replay for viewers and invalid run IDs or speeds", async () => {
    const path = `/api/v1/scenarios/${scenario.scenario_id}/replay`;
    await expect(demo.request(path, { method: "POST" }, viewer)).rejects.toMatchObject({ status: 403 });
    await expect(demo.request(path, { method: "POST", body: { scenario_run_id: "missing" } }, op)).rejects.toMatchObject({ status: 404 });
    await expect(demo.request(path, { method: "POST", body: { speed: -1 } }, op)).rejects.toMatchObject({ status: 422 });
  });
  it("requires a supervisor and an explanation; never auto-approves", async () => {
    const order = await create();
    expect(order.status).toBe("RECOMMENDED");
    await expect(decide(order, "approve", op)).rejects.toMatchObject({ code: "SUPERVISOR_REQUIRED" });
    await expect(decide(order, "approve", supervisor, " ")).rejects.toMatchObject({ code: "JUSTIFICATION_REQUIRED" });
    const approved = await decide(order, "approve");
    expect(approved.status).toBe("APPROVED");
    expect(approved.transitions[1]).toMatchObject({ actor_kind: "SCRIPTED_DEMO", actor_role: "MAINTENANCE_SUPERVISOR" });
    const completed = await decide(approved, "complete", op);
    expect(completed.status).toBe("COMPLETED");
    await expect(decide(completed, "approve")).rejects.toMatchObject({ code: "INVALID_TRANSITION" });
    expect(completed.transitions.some((t) => t.actor_kind === "HUMAN")).toBe(false);
  });
  it("supports rejection and evidence requests without invalid transitions", async () => {
    const order = await create();
    await expect(decide(order, "complete", op)).rejects.toMatchObject({ code: "INVALID_TRANSITION" });
    const needs = await decide(order, "request-evidence");
    expect(needs.status).toBe("NEEDS_EVIDENCE");
    await expect(decide(needs, "approve")).rejects.toMatchObject({ status: 409 });
    expect((await decide(needs, "reject")).status).toBe("REJECTED");
  });
  it("enforces idempotency and one work order per recommendation", async () => {
    const first = await create();
    expect(await create()).toEqual(first);
    await expect(create("new-key")).rejects.toMatchObject({ code: "WORK_ORDER_EXISTS" });
    await expect(demo.request("/api/v1/work-orders", { method: "POST", idempotencyKey: "create-key", body: { recommendation_id: "different" } }, op)).rejects.toMatchObject({ code: "IDEMPOTENCY_CONFLICT" });
  });
  it("updates overview counts and related asset and recommendation records", async () => {
    const order = await create();
    await decide(order, "approve");
    await expect(demo.request("/api/v1/overview", {}, op)).resolves.toMatchObject({ work_order_backlog: [{ status: "APPROVED", n: 1 }], decisions_by_actor_kind: [{ actor_kind: "SCRIPTED_DEMO", n: 1 }] });
    const recs = await demo.request("/api/v1/recommendations", {}, op) as { items: { recommendation_id: string; work_order_status: string }[] };
    expect(recs.items.find((r) => r.recommendation_id === recommendation.recommendation_id)?.work_order_status).toBe("APPROVED");
    await expect(demo.request(`/api/v1/assets/${order.asset_id}`, {}, op)).resolves.toMatchObject({ work_orders: [{ external_id: order.work_order_id, status: "APPROVED" }] });
  });
  it("persists only in session storage and resets without changing the source snapshot", async () => {
    await create();
    const restored = new DemoSession(snapshot, sessionStorage, "test-bundle", readRun, () => now);
    await expect(restored.request("/api/v1/work-orders", {}, op)).resolves.toMatchObject({ total: 1 });
    restored.reset();
    await expect(restored.request("/api/v1/work-orders", {}, op)).resolves.toMatchObject({ total: 0 });
    expect(snapshot.recommendations.every((r) => r.work_order_id === null)).toBe(true);
  });
  it("marks public evidence as omitted rather than inventing it", async () => {
    await expect(demo.request("/api/v1/inspections", {}, op)).resolves.toMatchObject({ evidence: { packaged: false, source: null, items: [], review_counts: [] } });
    await expect(demo.request("/api/v1/inspection-evidence/anything", {}, op)).rejects.toMatchObject({ status: 404 });
  });
  it("rejects a corrupt stored session instead of silently replacing it", () => {
    sessionStorage.setItem("fieldtwin.demo.session.bad", "broken");
    expect(() => new DemoSession(snapshot, sessionStorage, "bad", readRun)).toThrow(/Reset demo/);
  });
});
