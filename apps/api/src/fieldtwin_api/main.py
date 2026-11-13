"""FastAPI application factory.

uv run uvicorn --app-dir apps/api/src fieldtwin_api.main:app --port 8000
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import errors
from .context import HEADER, accept_or_new, correlation_id
from .routers import anomalies, data, decisions, facility, inspections, reports, scenarios, system
from .settings import DISCLOSURE, Settings, load_settings

log = logging.getLogger("fieldtwin_api")


def create_app(config: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="FieldTwin API",
        version="0.8.0",
        description=f"{DISCLOSURE}\n\nReads need no token. Every state change needs a bearer token; "
        "some need the MAINTENANCE_SUPERVISOR role.",
    )
    app.state.settings = config or load_settings()
    errors.install(app)

    @app.middleware("http")
    async def correlate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        token = correlation_id.set(accept_or_new(request.headers.get(HEADER)))
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:  # anything no handler caught; keep the correlation ID on the reply
                log.exception("unhandled error")
                response = JSONResponse(
                    status_code=500,
                    content=errors.body("INTERNAL_ERROR", "Unexpected error; see the server log."),
                )
            response.headers[HEADER] = correlation_id.get()
            log.info(
                json.dumps(
                    {
                        "correlation_id": correlation_id.get(),
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                )
            )
            return response
        finally:
            correlation_id.reset(token)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app.state.settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", HEADER],
        expose_headers=[HEADER, "Idempotent-Replayed"],
    )
    for module in (system, facility, data, scenarios, anomalies, inspections, decisions, reports):
        app.include_router(module.router)
    return app


logging.basicConfig(level=logging.INFO, format="%(message)s")
app = create_app()
