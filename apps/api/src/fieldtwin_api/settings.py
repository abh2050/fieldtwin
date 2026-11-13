"""Settings from the environment. Nothing here has a production default."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from packages.repositories.database import REPO_ROOT, database_url

ROLES = ("VIEWER", "OPERATOR", "MAINTENANCE_SUPERVISOR")
DISCLOSURE = (
    "AETHER Field is a fictional facility. Its assets, telemetry, alarms, and work orders are "
    "synthetic. Real public records (New Mexico OCD, Carbon Mapper, NAIP, Petrobras 3W) are labelled "
    "as such and are never presented as AETHER data."
)


@dataclass(frozen=True)
class Principal:
    actor_id: str
    role: str


@dataclass(frozen=True)
class Settings:
    database_url: str
    repo_root: Path
    # sha256(token) -> principal. Tokens themselves are never kept.
    tokens: dict[str, Principal] = field(default_factory=dict)
    cors_origins: tuple[str, ...] = ()


def parse_tokens(spec: str) -> dict[str, Principal]:
    """`actor:ROLE:token,actor:ROLE:token`. Malformed entries are refused, not skipped."""
    tokens: dict[str, Principal] = {}
    for entry in filter(None, (e.strip() for e in spec.split(","))):
        parts = entry.split(":", 2)
        if len(parts) != 3 or not all(parts):
            raise ValueError("FIELDTWIN_API_TOKENS entries must be actor:ROLE:token")
        actor, role, token = parts
        if role not in ROLES:
            raise ValueError(f"unknown role {role}; expected one of {', '.join(ROLES)}")
        if len(token) < 24:
            raise ValueError(f"the token for {actor} is shorter than 24 characters")
        tokens[hashlib.sha256(token.encode()).hexdigest()] = Principal(actor, role)
    return tokens


def load_settings() -> Settings:
    origins = os.environ.get(
        "FIELDTWIN_API_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
    )
    return Settings(
        database_url=database_url(),
        repo_root=Path(os.environ.get("FIELDTWIN_REPO_ROOT", REPO_ROOT)),
        tokens=parse_tokens(os.environ.get("FIELDTWIN_API_TOKENS", "")),
        cors_origins=tuple(o for o in origins.split(",") if o),
    )
