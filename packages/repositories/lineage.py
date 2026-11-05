"""Source-to-canonical lineage queries, from a canonical record to raw bytes and a process."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


def production_lineage(
    conn: psycopg.Connection, api_number: str, period: str, product_kind: str
) -> list[dict[str, Any]]:
    """Every production row for a well, month, and product, one per completion."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """SELECT * FROM v_production_lineage
               WHERE api_number = %s AND reporting_period = %s AND product_kind = %s
               ORDER BY reporting_entity_id""",
            (api_number, period, product_kind),
        )
        return cursor.fetchall()


def telemetry_lineage(conn: psycopg.Connection, event_id: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT * FROM v_telemetry_lineage WHERE event_id = %s", (event_id,))
        return cursor.fetchone()


def tag_semantics(conn: psycopg.Connection, native_tag: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT * FROM v_tag_semantics WHERE original_source_tag = %s", (native_tag,)
        )
        return cursor.fetchone()


def asset_exceptions(conn: psycopg.Connection, source_asset_id: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """SELECT exception_type, severity, field_name, original_values, evidence,
                      rule_id, disposition, status, decision_rationale
               FROM data_quality_exceptions WHERE source_asset_id = %s ORDER BY exception_id""",
            (source_asset_id,),
        )
        return cursor.fetchall()
