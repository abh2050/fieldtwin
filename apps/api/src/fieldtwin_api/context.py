"""Request correlation IDs."""

from __future__ import annotations

import contextvars
import re
import uuid

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")
_VALID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
HEADER = "X-Request-ID"


def accept_or_new(supplied: str | None) -> str:
    """Keep a caller's ID when it is safe to log; otherwise issue a fresh one."""
    return supplied if supplied and _VALID.match(supplied) else str(uuid.uuid4())
