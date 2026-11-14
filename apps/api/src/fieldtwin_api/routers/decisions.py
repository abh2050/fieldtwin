"""Recommendations and simulated work orders.

Creation and every decision go through the database's guarded path (migration 0015): the transition,
its audit event, and any approval record are written before the status changes, and the database
refuses anything the state machine or the role rules don't allow. Decisions made here are HUMAN;
scripted demonstration steps from the Gate 7 rebuild stay labelled SCRIPTED_DEMO.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, cast

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row, tuple_row
from pydantic import BaseModel, ConfigDict, Field

from packages.decision_engine.workflow import SUPERVISOR, Decision
from pipelines.decision.decide import record_decision

from .. import idempotency
from ..auth import require
from ..db import reader, writer
from ..errors import ApiError
from ..pagination import PageParams, page, page_params
from ..settings import Principal

router = APIRouter(prefix="/api/v1", tags=["decisions"])
Conn = psycopg.Connection[dict[str, Any]]
ENGINE = "decision-engine"


@router.get("/recommendations")
def recommendations(
    scenario_id: str | None = None,
    action: str | None = None,
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT r.recommendation_id, r.alarm_id, r.scenario_id, r.scenario_run_id, r.decided_at, r.action,
                  r.candidate_assets, r.suppressed_assets, r.priority_score, r.priority_band, r.respond_within_h,
                  r.terms, r.explanation, r.rules_version, r.provenance_class::text AS provenance_class,
                  w.external_id AS work_order_id, w.status AS work_order_status, count(*) OVER () AS _total
             FROM recommendations r LEFT JOIN work_orders w ON w.recommendation_id = r.recommendation_id
            WHERE (%(s)s::text IS NULL OR r.scenario_id = %(s)s) AND (%(a)s::text IS NULL OR r.action = %(a)s)
            ORDER BY r.priority_score DESC, r.decided_at LIMIT %(l)s OFFSET %(o)s""",
        {"s": scenario_id, "a": action, "l": params.limit, "o": params.offset},
    ).fetchall()
    total = rows[0]["_total"] if rows else 0
    for r in rows:
        del r["_total"]
    return page(rows, total, params)


def _orders(
    conn: Conn, external_id: str | None, status: str | None, params: PageParams
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT w.work_order_id AS _pk, w.external_id AS work_order_id, w.scenario_id, w.asset_id,
                  w.recommended_action, w.priority, w.priority_band, w.status, w.created_at, w.recommendation_id,
                  count(*) OVER () AS _total
             FROM work_orders w
            WHERE w.external_id IS NOT NULL
              AND (%(e)s::text IS NULL OR w.external_id = %(e)s) AND (%(st)s::text IS NULL OR w.status = %(st)s)
            ORDER BY w.created_at, w.external_id LIMIT %(l)s OFFSET %(o)s""",
        {"e": external_id, "st": status, "l": params.limit, "o": params.offset},
    ).fetchall()
    for r in rows:
        r["transitions"] = conn.execute(
            """SELECT sequence, decision, from_status, to_status, actor_id, actor_kind, actor_role, justification,
                      decided_at, recorded_at
                 FROM work_order_transitions WHERE work_order_id = %s ORDER BY sequence""",
            (r.pop("_pk"),),
        ).fetchall()
        r["decided_by_kinds"] = sorted(
            {t["actor_kind"] for t in r["transitions"] if t["decision"] != "CREATE"}
        )
    return rows


@router.get("/work-orders")
def work_orders(
    status: str | None = Query(
        None, description="RECOMMENDED, APPROVED, REJECTED, NEEDS_EVIDENCE, COMPLETED"
    ),
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
) -> dict[str, Any]:
    rows = _orders(conn, None, status, params)
    total = rows[0]["_total"] if rows else 0
    for r in rows:
        del r["_total"]
    return {
        "note": "Simulated work orders for fictional assets. Nothing here dispatches a crew or touches equipment.",
        **page(rows, total, params),
    }


def _one(conn: Conn, external_id: str) -> dict[str, Any]:
    rows = _orders(conn, external_id, None, PageParams(limit=1, offset=0))
    if not rows:
        raise ApiError(404, "WORK_ORDER_NOT_FOUND", f"No work order {external_id}.")
    rows[0].pop("_total", None)
    return rows[0]


class CreateWorkOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation_id: str = Field(min_length=1, max_length=64)


@router.post("/work-orders", status_code=201)
def create_work_order(
    body: CreateWorkOrder,
    request: Request,
    who: Principal = Depends(require("OPERATOR", SUPERVISOR)),
    conn: Conn = Depends(writer),
) -> Any:
    """Open a work order from a dispatching recommendation. The engine creates it; you are recorded as asking."""
    payload = body.model_dump()
    stored = idempotency.replay(conn, request, who, payload)
    if stored is not None:
        return stored
    rec = conn.execute(
        "SELECT * FROM recommendations WHERE recommendation_id = %s", (body.recommendation_id,)
    ).fetchone()
    if rec is None:
        raise ApiError(
            404, "RECOMMENDATION_NOT_FOUND", f"No recommendation {body.recommendation_id}."
        )
    if rec["action"] not in ("FIELD_INSPECTION", "CHECK_INSTRUMENTATION"):
        raise ApiError(
            409,
            "RECOMMENDATION_DOES_NOT_DISPATCH",
            f"{rec['recommendation_id']} recommends {rec['action']}.",
        )
    existing = conn.execute(
        "SELECT external_id FROM work_orders WHERE recommendation_id = %s",
        (rec["recommendation_id"],),
    ).fetchone()
    if existing:
        raise ApiError(
            409,
            "WORK_ORDER_EXISTS",
            f"{existing['external_id']} already covers this recommendation.",
        )
    external_id = "WO-" + hashlib.sha256(rec["recommendation_id"].encode()).hexdigest()[:12]
    pk = conn.execute(
        """INSERT INTO work_orders (scenario_id, asset_id, recommended_action, severity, priority, status,
             evidence_reference, external_id, recommendation_id, priority_band, created_at)
           VALUES (%s, %s, %s, %s, %s, 'RECOMMENDED', %s, %s, %s, %s, %s) RETURNING work_order_id""",
        (
            rec["scenario_id"],
            rec["candidate_assets"][0],
            rec["action"],
            rec["priority_band"],
            rec["priority_score"],
            rec["recommendation_id"],
            external_id,
            rec["recommendation_id"],
            rec["priority_band"],
            rec["decided_at"],
        ),
    ).fetchone()["work_order_id"]  # type: ignore[index]
    transition = conn.execute(
        """INSERT INTO work_order_transitions (work_order_id, sequence, decision, from_status, to_status, actor_id,
             actor_kind, actor_role, justification, decided_at)
           VALUES (%s, 0, 'CREATE', NULL, 'RECOMMENDED', %s, 'SYSTEM', 'DECISION_ENGINE', %s, %s)
           RETURNING transition_id""",
        (
            pk,
            ENGINE,
            f"Created from {rec['recommendation_id']} at the request of {who.actor_id} ({who.role}).",
            rec["decided_at"],
        ),
    ).fetchone()["transition_id"]  # type: ignore[index]
    conn.execute(
        """INSERT INTO audit_events (actor_id, operation, target_id, "timestamp", correlation_id,
             before_state_reference, after_state_reference) VALUES (%s, 'WORK_ORDER_CREATE', %s, %s, %s, NULL, 'RECOMMENDED')""",
        (who.actor_id, external_id, rec["decided_at"], f"transition:{transition}"),
    )
    response = _one(conn, external_id)
    response_json = _jsonable(response)
    idempotency.remember(conn, request, who, payload, 201, response_json)
    conn.commit()
    return JSONResponse(status_code=201, content=response_json)


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    justification: str = Field(min_length=1, max_length=2000)
    decided_at: datetime | None = Field(
        None, description="scenario-clock time; defaults to the latest transition's time"
    )


def _jsonable(value: Any) -> Any:
    return json.loads(
        json.dumps(value, default=lambda v: v.isoformat() if hasattr(v, "isoformat") else str(v))
    )


def _decide(
    conn: Conn,
    request: Request,
    who: Principal,
    external_id: str,
    decision: Decision,
    body: DecisionBody,
) -> Any:
    payload = body.model_dump(mode="json")
    stored = idempotency.replay(conn, request, who, payload)
    if stored is not None:
        return stored
    if not body.justification.strip():
        raise ApiError(422, "JUSTIFICATION_REQUIRED", "A decision needs a justification.")
    latest = conn.execute(
        """SELECT max(t.decided_at) AS at FROM work_order_transitions t JOIN work_orders w USING (work_order_id)
            WHERE w.external_id = %s""",
        (external_id,),
    ).fetchone()
    if latest is None or latest["at"] is None:
        raise ApiError(404, "WORK_ORDER_NOT_FOUND", f"No work order {external_id}.")
    at = body.decided_at or latest["at"]
    conn.row_factory = tuple_row  # type: ignore[assignment]  # record_decision reads tuples
    try:
        record_decision(
            cast("psycopg.Connection[Any]", conn),
            external_id,
            decision,
            who.actor_id,
            "HUMAN",
            who.role,
            body.justification.strip(),
            at,
        )
    except ValueError as exc:
        raise ApiError(409, "INVALID_TRANSITION", str(exc)) from exc
    finally:
        conn.row_factory = dict_row  # type: ignore[assignment]
    response = _jsonable(_one(conn, external_id))
    idempotency.remember(conn, request, who, payload, 200, response)
    conn.commit()
    return response


@router.post("/work-orders/{work_order_id}/approve")
def approve(
    work_order_id: str,
    body: DecisionBody,
    request: Request,
    who: Principal = Depends(require(SUPERVISOR)),
    conn: Conn = Depends(writer),
) -> Any:
    return _decide(conn, request, who, work_order_id, Decision.APPROVE, body)


@router.post("/work-orders/{work_order_id}/reject")
def reject(
    work_order_id: str,
    body: DecisionBody,
    request: Request,
    who: Principal = Depends(require(SUPERVISOR)),
    conn: Conn = Depends(writer),
) -> Any:
    return _decide(conn, request, who, work_order_id, Decision.REJECT, body)


@router.post("/work-orders/{work_order_id}/request-evidence")
def request_evidence(
    work_order_id: str,
    body: DecisionBody,
    request: Request,
    who: Principal = Depends(require(SUPERVISOR)),
    conn: Conn = Depends(writer),
) -> Any:
    return _decide(conn, request, who, work_order_id, Decision.REQUEST_EVIDENCE, body)


@router.post("/work-orders/{work_order_id}/complete")
def complete(
    work_order_id: str,
    body: DecisionBody,
    request: Request,
    who: Principal = Depends(require("OPERATOR", SUPERVISOR)),
    conn: Conn = Depends(writer),
) -> Any:
    """Record that the simulated visit happened. It reports nothing about what was found."""
    return _decide(conn, request, who, work_order_id, Decision.COMPLETE, body)
