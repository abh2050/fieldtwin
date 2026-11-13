"""Database sessions through the least-privilege `fieldtwin_app` role (ADR 0015).

Each request gets one connection and one transaction. Reads run READ ONLY; writes run as the
application role, which can insert only into the human workflow tables.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
from fastapi import Depends, Request
from psycopg.rows import dict_row

from .settings import Settings

APP_ROLE = "fieldtwin_app"


def _connect(config: Settings, read_only: bool) -> psycopg.Connection[dict[str, Any]]:
    conn = psycopg.connect(config.database_url, row_factory=dict_row, connect_timeout=5)
    conn.read_only = read_only
    conn.execute(f"SET ROLE {APP_ROLE}")
    conn.execute("SET statement_timeout = '15s'")
    return conn


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def reader(config: Settings = Depends(_settings)) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    conn = _connect(config, read_only=True)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def writer(config: Settings = Depends(_settings)) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    conn = _connect(config, read_only=False)
    try:
        yield conn
    finally:
        conn.rollback()  # anything not explicitly committed is discarded
        conn.close()
