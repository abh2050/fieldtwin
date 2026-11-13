"""Source systems, ingestion batches, data quality, and record lineage."""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends

from ..db import reader
from ..errors import ApiError
from ..pagination import PageParams, page, page_params

router = APIRouter(prefix="/api/v1", tags=["data"])
Conn = psycopg.Connection[dict[str, Any]]


def _strip_total(rows: list[dict[str, Any]]) -> int:
    total = rows[0]["_total"] if rows else 0
    for r in rows:
        del r["_total"]
    return int(total)


@router.get("/data-sources")
def data_sources(conn: Conn = Depends(reader)) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT s.source_system_id, s.provider, s.source_url, s.source_version, s.license,
                  s.retrieval_timestamp, s.usage_constraints, s.is_project_generated,
                  (SELECT count(*) FROM ingestion_batches b WHERE b.source_system_id = s.source_system_id) AS batches,
                  (SELECT count(*) FROM observations o WHERE o.source_system_id = s.source_system_id) AS observations
             FROM source_systems s ORDER BY s.is_project_generated, s.source_system_id"""
    ).fetchall()
    return {"items": rows, "total": len(rows)}


@router.get("/ingestion-runs")
def ingestion_runs(
    source_system_id: str | None = None,
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT b.batch_id, b.source_system_id, b.source_version, b.ingestion_timestamp, b.original_checksum,
                  b.source_record_count, b.accepted_count, b.rejected_count, b.processing_status, b.manifest_uri,
                  (SELECT count(*) FROM batch_files f WHERE f.batch_id = b.batch_id) AS files,
                  count(*) OVER () AS _total
             FROM ingestion_batches b
            WHERE (%(s)s::text IS NULL OR b.source_system_id = %(s)s)
            ORDER BY b.ingestion_timestamp DESC LIMIT %(l)s OFFSET %(o)s""",
        {"s": source_system_id, "l": params.limit, "o": params.offset},
    ).fetchall()
    return page(rows, _strip_total(rows), params)


@router.get("/data-quality")
def data_quality(
    exception_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    source_system_id: str | None = None,
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
) -> dict[str, Any]:
    filters = {"t": exception_type, "v": severity, "st": status, "s": source_system_id}
    where = """(%(t)s::text IS NULL OR exception_type = %(t)s) AND (%(v)s::text IS NULL OR severity = %(v)s)
               AND (%(st)s::text IS NULL OR status = %(st)s)
               AND (%(s)s::text IS NULL OR source_system_id = %(s)s)"""
    summary = conn.execute(
        f"""SELECT exception_type, severity, status, source_system_id, count(*) AS exceptions
              FROM data_quality_exceptions WHERE {where}
             GROUP BY 1, 2, 3, 4 ORDER BY exceptions DESC""",
        filters,
    ).fetchall()
    rows = conn.execute(
        f"""SELECT exception_id, exception_type, severity, source_system_id, batch_id, dataset, source_record_key,
                   field_name, rule_id, disposition, status, decision_rationale, detected_at,
                   count(*) OVER () AS _total
              FROM data_quality_exceptions WHERE {where}
             ORDER BY exception_id LIMIT %(l)s OFFSET %(o)s""",
        {**filters, "l": params.limit, "o": params.offset},
    ).fetchall()
    return {"summary": summary, **page(rows, _strip_total(rows), params)}


KINDS = ("observation", "production", "telemetry_event")


@router.get("/lineage/{record_id}")
def lineage(record_id: str, conn: Conn = Depends(reader)) -> dict[str, Any]:
    """`record_id` is kind:id, e.g. observation:12, production:7, or telemetry_event:X."""
    kind, _, key = record_id.partition(":")
    if kind not in KINDS or not key:
        raise ApiError(
            422,
            "INVALID_RECORD_ID",
            f"Use kind:id with kind one of {', '.join(KINDS)}.",
            {"record_id": record_id},
        )
    chain: dict[str, Any] | None
    if kind == "production":
        if not key.isdigit():
            raise ApiError(422, "INVALID_RECORD_ID", "A production record ID is a number.")
        chain = conn.execute(
            "SELECT * FROM v_production_lineage WHERE record_id = %s", (int(key),)
        ).fetchone()
    elif kind == "telemetry_event":
        chain = conn.execute(
            "SELECT * FROM v_telemetry_lineage WHERE event_id = %s", (key,)
        ).fetchone()
    else:
        if not key.isdigit():
            raise ApiError(422, "INVALID_RECORD_ID", "An observation ID is a number.")
        observation = conn.execute(
            """SELECT o.observation_id, o.source_system_id, o.source_record_id, o.observation_type, o.metric_name,
                      o.provenance_class::text AS provenance_class, o.original_record_uri, o.batch_id,
                      o.transformation_id, o.scenario_id, o.scenario_run_id, o.sensor_tag_id
                 FROM observations o WHERE o.observation_id = %s""",
            (int(key),),
        ).fetchone()
        if observation is None:
            chain = None
        else:
            chain = {"observation": observation}
            synthetic = conn.execute(
                "SELECT * FROM v_synthetic_provenance_chain WHERE observation_id = %s", (int(key),)
            ).fetchone()
            if synthetic:
                chain["synthetic_chain"] = synthetic
            if observation["batch_id"]:
                chain["batch"] = conn.execute(
                    """SELECT batch_id, source_system_id, source_version, ingestion_timestamp, original_checksum,
                              manifest_uri FROM ingestion_batches WHERE batch_id = %s""",
                    (observation["batch_id"],),
                ).fetchone()
            if observation["transformation_id"]:
                chain["transformation"] = conn.execute(
                    "SELECT * FROM transformations WHERE transformation_id = %s",
                    (observation["transformation_id"],),
                ).fetchone()
    if chain is None:
        raise ApiError(404, "RECORD_NOT_FOUND", f"No {kind} record {key}.")
    for value in chain.values() if isinstance(chain, dict) else ():
        if isinstance(value, dict) and "provenance_class" in value:
            value["provenance_class"] = str(value["provenance_class"])
    if "provenance_class" in chain:
        chain["provenance_class"] = str(chain["provenance_class"])
    return {"record_id": record_id, "kind": kind, "lineage": chain}
