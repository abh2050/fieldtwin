"""Live smoke test of a running Gate 8 API: every read endpoint, then the full work-order and replay
workflow, through HTTP exactly as the web app calls it. Prints a JSON summary; exits 1 on any failure.

    FIELDTWIN_SMOKE_TOKENS=actor:ROLE:token,... uv run python scripts/gate8_smoke.py http://127.0.0.1:8000

Needs a database from `make app-db` (recommendations loaded, no work orders). It changes that
database: it opens, approves, and completes one work order, and plays and pauses one replay.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

READS = [
    "/health",
    "/api/v1/facilities",
    "/api/v1/assets?limit=5",
    "/api/v1/assets/GS-A",
    "/api/v1/assets/GS-A/relationships",
    "/api/v1/assets/A-01/observations?limit=5",
    "/api/v1/network",
    "/api/v1/data-sources",
    "/api/v1/ingestion-runs",
    "/api/v1/data-quality?limit=5",
    "/api/v1/lineage/observation:1",
    "/api/v1/scenarios",
    "/api/v1/scenarios/AETHER-FAULT-001-NET/runs/AETHER-FAULT-001-NET:v1:fault/tags",
    "/api/v1/scenarios/AETHER-FAULT-001-NET/runs/AETHER-FAULT-001-NET:v1:fault/telemetry?tag=GS-A.DPT-NET",
    "/api/v1/anomalies",
    "/api/v1/model-evaluations",
    "/api/v1/inspections?limit=5",
    "/api/v1/recommendations",
    "/api/v1/work-orders",
    "/api/v1/economics/comparison",
    "/api/v1/audit-events",
    "/api/v1/reports",
    "/api/v1/reports/d1",
    "/api/v1/diagnostics/d1",
    "/api/v1/overview",
]


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    tokens = {
        role: token
        for _, role, token in (
            e.split(":", 2) for e in os.environ["FIELDTWIN_SMOKE_TOKENS"].split(",")
        )
    }
    failures: list[str] = []
    results: dict[str, Any] = {"reads": {}, "workflow": []}
    with httpx.Client(base_url=base, timeout=30) as http:
        for path in READS:
            r = http.get(path)
            results["reads"][path] = r.status_code
            if r.status_code != 200:
                failures.append(f"GET {path} -> {r.status_code} {r.text[:200]}")
        anomalies = http.get("/api/v1/anomalies").json()["items"]
        if anomalies:
            r = http.get(f"/api/v1/anomalies/{anomalies[0]['alarm_id']}")
            results["reads"]["/api/v1/anomalies/{id}"] = r.status_code
        cards = http.get("/api/v1/inspections?limit=1").json()["evidence"]["items"]
        if cards:
            r = http.get(f"/api/v1/inspection-evidence/{cards[0]['evidence_id']}")
            results["reads"]["/api/v1/inspection-evidence/{id}"] = r.status_code
            chip = http.get(f"/api/v1/inspection-evidence/{cards[0]['chip_id']}/chip.png")
            results["reads"]["/api/v1/inspection-evidence/{chip}/chip.png"] = chip.status_code
            if chip.headers.get("content-type") != "image/png":
                failures.append("chip is not a PNG")

        def step(
            name: str,
            method: str,
            path: str,
            role: str | None,
            body: Any,
            expect: int,
            key: str | None = None,
        ) -> Any:
            headers = {"Authorization": f"Bearer {tokens[role]}"} if role else {}
            if key:
                headers["Idempotency-Key"] = key
            r = http.request(method, path, json=body, headers=headers)
            results["workflow"].append({"step": name, "status": r.status_code, "expected": expect})
            if r.status_code != expect:
                failures.append(f"{name}: {r.status_code} (expected {expect}) {r.text[:200]}")
            return r

        recs = [
            r
            for r in http.get("/api/v1/recommendations").json()["items"]
            if r["priority_band"] and not r["work_order_id"]
        ]
        if not recs:
            failures.append("no open dispatching recommendation; run make app-db first")
        else:
            rec = recs[0]["recommendation_id"]
            step(
                "create without a token",
                "POST",
                "/api/v1/work-orders",
                None,
                {"recommendation_id": rec},
                401,
            )
            step(
                "create as viewer",
                "POST",
                "/api/v1/work-orders",
                "VIEWER",
                {"recommendation_id": rec},
                403,
            )
            created = step(
                "create as operator",
                "POST",
                "/api/v1/work-orders",
                "OPERATOR",
                {"recommendation_id": rec},
                201,
                "smoke-create-0001",
            )
            step(
                "same key again",
                "POST",
                "/api/v1/work-orders",
                "OPERATOR",
                {"recommendation_id": rec},
                201,
                "smoke-create-0001",
            )
            step(
                "duplicate order",
                "POST",
                "/api/v1/work-orders",
                "OPERATOR",
                {"recommendation_id": rec},
                409,
            )
            wo = created.json().get("work_order_id", "missing")
            why = {"justification": "Gate 8 smoke test: reviewed the explanation and candidates."}
            step(
                "approve as operator",
                "POST",
                f"/api/v1/work-orders/{wo}/approve",
                "OPERATOR",
                why,
                403,
            )
            approved = step(
                "approve as supervisor",
                "POST",
                f"/api/v1/work-orders/{wo}/approve",
                "MAINTENANCE_SUPERVISOR",
                why,
                200,
            )
            step(
                "approve twice",
                "POST",
                f"/api/v1/work-orders/{wo}/approve",
                "MAINTENANCE_SUPERVISOR",
                why,
                409,
            )
            step(
                "complete",
                "POST",
                f"/api/v1/work-orders/{wo}/complete",
                "OPERATOR",
                {"justification": "Simulated visit recorded."},
                200,
            )
            kinds = [t["actor_kind"] for t in approved.json().get("transitions", [])]
            results["approved_transition_kinds"] = kinds
            if kinds != ["SYSTEM", "HUMAN"]:
                failures.append(f"unexpected actor kinds {kinds}")
            audit = http.get("/api/v1/audit-events", params={"target_id": wo}).json()["items"]
            results["audit_events_for_work_order"] = [
                (e["operation"], e["actor_id"]) for e in audit
            ]
            if len(audit) != 3:
                failures.append(f"expected 3 audit events, found {len(audit)}")
        scenario = "/api/v1/scenarios/AETHER-NET-NORMAL"
        step("replay", "POST", f"{scenario}/replay", "OPERATOR", {"speed": 600}, 200)
        step("replay while playing", "POST", f"{scenario}/replay", "OPERATOR", None, 409)
        step("pause", "POST", f"{scenario}/pause", "OPERATOR", None, 200)
        step("reset", "POST", f"{scenario}/reset", "MAINTENANCE_SUPERVISOR", None, 200)
    results["failures"] = failures
    print(json.dumps(results, indent=1))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
