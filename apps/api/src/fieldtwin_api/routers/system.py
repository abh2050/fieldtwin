"""Health and the disclosure every screen shows."""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import principal, settings
from ..db import APP_ROLE
from ..settings import DISCLOSURE, Principal, Settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health(config: Settings = Depends(settings)) -> JSONResponse:
    """Database reachability, the role in use, and applied migrations. 503 when degraded."""
    checks: dict[str, Any] = {"database": "unreachable"}
    try:
        with psycopg.connect(config.database_url, connect_timeout=3) as conn:
            conn.execute(f"SET ROLE {APP_ROLE}")
            row = conn.execute(
                "SELECT current_user, (SELECT count(*) FROM schema_migrations), "
                "(SELECT max(version) FROM schema_migrations)"
            ).fetchone()
            assert row is not None
            checks = {
                "database": "ok",
                "role": row[0],
                "migrations_applied": row[1],
                "latest_migration": row[2],
            }
    except (psycopg.Error, AssertionError) as exc:
        checks["detail"] = type(exc).__name__
    ok = checks["database"] == "ok"
    checks["writes_enabled"] = bool(config.tokens)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "checks": checks, "disclosure": DISCLOSURE},
    )


@router.get("/api/v1/disclosure")
def disclosure() -> dict[str, str]:
    return {"disclosure": DISCLOSURE}


@router.get("/api/v1/me")
def me(who: Principal = Depends(principal)) -> dict[str, str]:
    """Who a bearer token belongs to, so a client can explain which actions it may take."""
    return {"actor_id": who.actor_id, "role": who.role}
