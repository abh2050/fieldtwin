"""Facilities, fictional assets, relationships, the network schematic, and per-asset observations."""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query

from ..db import reader
from ..errors import ApiError
from ..pagination import PageParams, page, page_params

router = APIRouter(prefix="/api/v1", tags=["facility"])
Conn = psycopg.Connection[dict[str, Any]]


@router.get("/facilities")
def facilities(conn: Conn = Depends(reader)) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT f.facility_id, f.facility_name, f.facility_type, f.region, f.is_fictional, f.disclosure,
                  (SELECT count(*) FROM assets a WHERE a.facility_id = f.facility_id) AS asset_count
             FROM facilities f ORDER BY f.facility_id"""
    ).fetchall()
    return {"items": rows, "total": len(rows)}


ASSET_COLUMNS = """a.asset_id, a.facility_id, a.parent_asset_id, a.asset_type, a.asset_name,
  a.equipment_class_id, a.operating_status, a.is_fictional, a.provenance_class::text AS provenance_class,
  a.transformation_id"""


@router.get("/assets")
def assets(
    asset_type: str | None = Query(None, description="WELL, PAD, COMPRESSOR, ..."),
    parent_asset_id: str | None = None,
    q: str | None = Query(None, max_length=64, description="substring of the ID or name"),
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
) -> dict[str, Any]:
    rows = conn.execute(
        f"""SELECT {ASSET_COLUMNS}, count(*) OVER () AS _total FROM assets a
             WHERE (%(t)s::text IS NULL OR a.asset_type = %(t)s)
               AND (%(p)s::text IS NULL OR a.parent_asset_id = %(p)s)
               AND (%(q)s::text IS NULL OR a.asset_id ILIKE '%%' || %(q)s || '%%'
                    OR a.asset_name ILIKE '%%' || %(q)s || '%%')
             ORDER BY a.asset_id LIMIT %(l)s OFFSET %(o)s""",
        {"t": asset_type, "p": parent_asset_id, "q": q, "l": params.limit, "o": params.offset},
    ).fetchall()
    total = rows[0]["_total"] if rows else 0
    for r in rows:
        del r["_total"]
    return page(rows, total, params)


def _asset(conn: Conn, asset_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {ASSET_COLUMNS} FROM assets a WHERE a.asset_id = %s", (asset_id,)
    ).fetchone()
    if row is None:
        raise ApiError(404, "ASSET_NOT_FOUND", f"No fictional asset {asset_id}.")
    return row


@router.get("/assets/{asset_id}")
def asset(asset_id: str, conn: Conn = Depends(reader)) -> dict[str, Any]:
    row = _asset(conn, asset_id)
    row["children"] = [
        r["asset_id"]
        for r in conn.execute(
            "SELECT asset_id FROM assets WHERE parent_asset_id = %s ORDER BY asset_id", (asset_id,)
        ).fetchall()
    ]
    row["sensors"] = conn.execute(
        """SELECT tag_id, native_tag_name, canonical_metric, physical_quantity, unit_id,
                  pressure_reference_type::text AS pressure_reference_type, sampling_frequency
             FROM sensor_tags WHERE fictional_asset_id = %s ORDER BY native_tag_name""",
        (asset_id,),
    ).fetchall()
    row["network_nodes"] = conn.execute(
        "SELECT node_id, node_type, local_x_m, local_y_m FROM physical_nodes WHERE asset_id = %s",
        (asset_id,),
    ).fetchall()
    row["work_orders"] = conn.execute(
        """SELECT external_id, status, priority_band, created_at FROM work_orders
            WHERE asset_id = %s AND external_id IS NOT NULL ORDER BY created_at""",
        (asset_id,),
    ).fetchall()
    return row


@router.get("/assets/{asset_id}/relationships")
def relationships(asset_id: str, conn: Conn = Depends(reader)) -> dict[str, Any]:
    _asset(conn, asset_id)
    declared = conn.execute(
        """SELECT relationship_id, source_asset_id, target_asset_id, relationship_type, evidence_type,
                  provenance_class::text AS provenance_class, effective_from::text AS effective_from, effective_to::text AS effective_to
             FROM asset_relationships WHERE source_asset_id = %(a)s OR target_asset_id = %(a)s
             ORDER BY relationship_id""",
        {"a": asset_id},
    ).fetchall()
    physical = conn.execute(
        """SELECT e.edge_id, e.edge_type, e.from_node_id, e.to_node_id, fa.asset_id AS from_asset_id,
                  ta.asset_id AS to_asset_id, e.element_asset_id, e.length_m, e.diameter_m, e.network_version
             FROM physical_edges e
             JOIN physical_nodes fa ON fa.node_id = e.from_node_id
             JOIN physical_nodes ta ON ta.node_id = e.to_node_id
            WHERE e.element_asset_id = %(a)s OR fa.asset_id = %(a)s OR ta.asset_id = %(a)s
            ORDER BY e.edge_id""",
        {"a": asset_id},
    ).fetchall()
    return {"asset_id": asset_id, "declared": declared, "physical": physical}


@router.get("/assets/{asset_id}/observations")
def observations(
    asset_id: str,
    scenario_run_id: str | None = None,
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
) -> dict[str, Any]:
    """Stored observation records for the asset's sensors: one summary row per sensor and run."""
    _asset(conn, asset_id)
    rows = conn.execute(
        """SELECT o.observation_id, o.source_record_id, o.observation_type, o.metric_name, o.unit_id,
                  o.quality_flag, o.provenance_class::text AS provenance_class, o.value_count, o.null_count,
                  o.scenario_id, o.scenario_run_id, o.original_record_uri, count(*) OVER () AS _total
             FROM observations o JOIN sensor_tags t ON t.tag_id = o.sensor_tag_id
            WHERE t.fictional_asset_id = %(a)s
              AND (%(r)s::text IS NULL OR o.scenario_run_id = %(r)s)
            ORDER BY o.scenario_run_id, o.metric_name LIMIT %(l)s OFFSET %(o)s""",
        {"a": asset_id, "r": scenario_run_id, "l": params.limit, "o": params.offset},
    ).fetchall()
    total = rows[0]["_total"] if rows else 0
    for r in rows:
        del r["_total"]
    return page(rows, total, params)


@router.get("/network")
def network(conn: Conn = Depends(reader)) -> dict[str, Any]:
    """The fictional gathering network in local metres. AETHER Field has no real location."""
    nodes = conn.execute(
        """SELECT n.node_id, n.node_type, n.asset_id, n.local_x_m, n.local_y_m, n.network_version,
                  a.asset_type, a.parent_asset_id
             FROM physical_nodes n LEFT JOIN assets a USING (asset_id) ORDER BY n.node_id"""
    ).fetchall()
    edges = conn.execute(
        """SELECT edge_id, edge_type, from_node_id, to_node_id, element_asset_id, valve_asset_id,
                  length_m, diameter_m FROM physical_edges ORDER BY edge_id"""
    ).fetchall()
    return {
        "coordinate_system": "LOCAL_METRES",
        "note": "Schematic coordinates of a fictional facility. Not a geographic location.",
        "nodes": nodes,
        "edges": edges,
    }
