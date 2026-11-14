"""Idempotency-Key support for state-changing requests.

The first successful response for (caller, key) is stored in the same transaction as the change. A
repeat with the same request body gets that response back with `Idempotent-Replayed: true` and has no
second effect. The same key with a different body is refused. Failures are not stored, so a caller
can retry them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from fastapi import Request
from fastapi.responses import JSONResponse

from .errors import ApiError
from .settings import Principal

HEADER = "Idempotency-Key"


def request_hash(method: str, path: str, payload: Any) -> str:
    canonical = json.dumps({"m": method, "p": path, "b": payload}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def replay(
    conn: psycopg.Connection[dict[str, Any]],
    request: Request,
    who: Principal,
    payload: Any,
) -> JSONResponse | None:
    key = request.headers.get(HEADER)
    if not key:
        return None
    row = conn.execute(
        """SELECT request_sha256, status_code, response FROM api_idempotency_keys
            WHERE actor_id = %s AND idempotency_key = %s""",
        (who.actor_id, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_sha256"] != request_hash(request.method, request.url.path, payload):
        raise ApiError(
            422,
            "IDEMPOTENCY_KEY_REUSED",
            "This Idempotency-Key was already used for a different request.",
        )
    return JSONResponse(
        status_code=row["status_code"],
        content=row["response"],
        headers={"Idempotent-Replayed": "true"},
    )


def remember(
    conn: psycopg.Connection[dict[str, Any]],
    request: Request,
    who: Principal,
    payload: Any,
    status: int,
    response: Any,
) -> None:
    key = request.headers.get(HEADER)
    if not key:
        return
    try:
        conn.execute(
            """INSERT INTO api_idempotency_keys (actor_id, idempotency_key, method, path, request_sha256,
                 status_code, response) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                who.actor_id,
                key,
                request.method,
                request.url.path,
                request_hash(request.method, request.url.path, payload),
                status,
                json.dumps(response, default=str),
            ),
        )
    except psycopg.errors.CheckViolation as exc:
        raise ApiError(
            422,
            "IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key must be 8 to 128 of A-Z a-z 0-9 . _ : -",
        ) from exc
