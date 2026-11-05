"""PostgreSQL connection and a small, checksum-verified migration runner."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "db" / "migrations"
DEFAULT_URL = "postgresql://fieldtwin:change-me-local-only@127.0.0.1:55432/fieldtwin"


class MigrationError(RuntimeError):
    """An applied migration no longer matches its file."""


def database_url() -> str:
    return os.environ.get("FIELDTWIN_DB_URL", DEFAULT_URL)


def connect(url: str | None = None, **kwargs) -> psycopg.Connection:
    return psycopg.connect(url or database_url(), **kwargs)


def migrate(conn: psycopg.Connection, directory: Path = MIGRATIONS) -> list[str]:
    """Apply pending migrations, each in its own transaction. Returns the versions applied."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
             version text PRIMARY KEY,
             sha256 text NOT NULL,
             applied_at timestamptz NOT NULL DEFAULT now()
           )"""
    )
    conn.commit()
    applied: dict[str, str] = dict(
        conn.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
    )
    done = []
    for path in sorted(directory.glob("*.sql")):
        body = path.read_text()
        digest = hashlib.sha256(body.encode()).hexdigest()
        if path.name in applied:
            if applied[path.name] != digest:
                raise MigrationError(
                    f"{path.name} changed after it was applied. Add a new migration."
                )
            continue
        with conn.transaction():
            conn.execute(body.encode())
            conn.execute(
                "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
                (path.name, digest),
            )
        done.append(path.name)
    return done


def scalar(conn: psycopg.Connection, sql: str) -> Any:
    """Return the first column of a query that must produce a row."""
    row = conn.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(f"query returned no rows: {sql}")
    return row[0]


def main() -> int:
    with connect() as conn:
        version = scalar(conn, "SHOW server_version")
        print(f"server_version={version}")
        applied = migrate(conn)
        postgis = scalar(conn, "SELECT postgis_version()")
        print(f"postgis_version={postgis}")
        for name in applied:
            print(f"applied {name}")
        print(f"migrations_applied={len(applied)}")
        tables = scalar(
            conn,
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "AND table_name <> 'spatial_ref_sys'",
        )
        print(f"tables_in_public={tables}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
