"""One error shape for every failure: {"error": {code, message, correlation_id, details}}."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .context import correlation_id

log = logging.getLogger("fieldtwin_api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "correlation_id": correlation_id.get(),
            "details": details,
        }
    }


def _respond(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=jsonable_encoder(body(code, message, details)))


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _respond(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"location": list(e.get("loc", ())), "message": e.get("msg", "")} for e in exc.errors()
        ]
        return _respond(422, "VALIDATION_FAILED", "The request is not valid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return _respond(exc.status_code, code, str(exc.detail))

    @app.exception_handler(psycopg.errors.CheckViolation)
    async def refused(_: Request, exc: psycopg.errors.CheckViolation) -> JSONResponse:
        # The database's own guards (transitions, roles, append-only) refused the change.
        return _respond(409, "REFUSED_BY_DATABASE", (exc.diag.message_primary or str(exc)))

    @app.exception_handler(psycopg.errors.InsufficientPrivilege)
    async def forbidden(_: Request, exc: psycopg.errors.InsufficientPrivilege) -> JSONResponse:
        return _respond(403, "FORBIDDEN_BY_DATABASE", "The application role may not do this.")

    @app.exception_handler(psycopg.OperationalError)
    async def unavailable(_: Request, exc: psycopg.OperationalError) -> JSONResponse:
        log.warning("database unavailable: %s", exc)
        return _respond(503, "DATABASE_UNAVAILABLE", "The database is not reachable.")
