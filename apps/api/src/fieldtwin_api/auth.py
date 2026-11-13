"""Bearer-token authentication for state-changing requests.

Locally, tokens come from FIELDTWIN_API_TOKENS (see `make app-tokens`). Gate 9 replaces this with a
managed identity provider. Reads need no token; every write needs one, and some need a role. The
database enforces roles again (a supervisor decision from another role is refused there too).
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Depends, Request

from .errors import ApiError
from .settings import Principal, Settings


def settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def principal(request: Request, config: Settings = Depends(settings)) -> Principal:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "This request needs a bearer token.")
    digest = hashlib.sha256(token.encode()).hexdigest()
    for known, who in config.tokens.items():
        if hmac.compare_digest(known, digest):
            return who
    raise ApiError(401, "AUTHENTICATION_FAILED", "The bearer token is not recognised.")


def require(*roles: str):  # type: ignore[no-untyped-def]
    def check(who: Principal = Depends(principal)) -> Principal:
        if who.role not in roles:
            raise ApiError(
                403, "FORBIDDEN", f"This needs the role {' or '.join(roles)}; you are {who.role}."
            )
        return who

    return check
