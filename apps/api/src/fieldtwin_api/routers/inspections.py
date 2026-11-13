"""Inspection requests for fictional assets, and Gate 6 aerial evidence about real public records.

The two never mix: aerial evidence describes real registered wells near real plumes, as proximity
only. Inspection requests concern fictional AETHER assets in simulated scenarios.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from ..auth import settings
from ..db import reader
from ..errors import ApiError
from ..pagination import PageParams, page, page_params
from ..results import read_json, resolve
from ..settings import Settings

router = APIRouter(prefix="/api/v1", tags=["inspections"])
Conn = psycopg.Connection[dict[str, Any]]
CARDS = "data/gold/inspection/evidence_cards.json"
CHIP_ID = re.compile(r"^CHIP-[0-9a-f]{12}$")


def _cards(config: Settings) -> tuple[list[dict[str, Any]], dict[str, str]]:
    cards, source = read_json(config.repo_root, CARDS, "make gate6")
    return cards, source


@router.get("/inspections")
def inspections(
    coverage_status: str | None = Query(None, description="PLUME_NEARBY or IMAGED_NO_PLUME_NEARBY"),
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    requests = conn.execute(
        """SELECT request_id, asset_id, affected_asset_id, scenario_id, scenario_run_id, trigger_event_id,
                  inspection_type, reason, status, created_at, provenance_class::text AS provenance_class
             FROM inspection_requests ORDER BY created_at"""
    ).fetchall()
    reviews = conn.execute(
        "SELECT evidence_id, outcome, count(*) AS n FROM inspection_review_events GROUP BY 1, 2"
    ).fetchall()
    reviewed = {r["evidence_id"] for r in reviews}
    cards, source = _cards(config)
    chosen = [
        c for c in cards if coverage_status is None or c["coverage_status"] == coverage_status
    ]
    items = [
        {
            "evidence_id": c["chip"]["chip_id"] if c.get("chip") else c["source_asset_id"],
            "source_asset_id": c["source_asset_id"],
            "headline": c["headline"],
            "coverage_status": c["coverage_status"],
            "plume_count": len(c.get("plumes", [])),
            "nearest_plume_m": min((p["distance_m"] for p in c.get("plumes", [])), default=None),
            "chip_id": c["chip"]["chip_id"] if c.get("chip") else None,
            "footprint_wgs84": c["chip"]["footprint_wgs84"] if c.get("chip") else None,
            "reviewed": bool(c.get("chip") and c["chip"]["chip_id"] in reviewed),
            "provenance": c["provenance"],
        }
        for c in chosen[params.offset : params.offset + params.limit]
    ]
    return {
        "requests": {"items": requests, "total": len(requests), "provenance_class": "SYNTHETIC"},
        "evidence": {
            "source": source,
            "record_kind": "REAL_PUBLIC_RECORDS",
            "note": "Real registered wells near real plume detections. Spatial proximity only, not source "
            "attribution. None of this describes AETHER Field.",
            "coverage_counts": dict(Counter(c["coverage_status"] for c in cards)),
            "review_counts": reviews,
            **page(items, len(chosen), params),
        },
    }


def _card(config: Settings, evidence_id: str) -> dict[str, Any]:
    cards, source = _cards(config)
    for c in cards:
        if (c.get("chip") and c["chip"]["chip_id"] == evidence_id) or c[
            "source_asset_id"
        ] == evidence_id:
            return {**c, "source": source}
    raise ApiError(404, "EVIDENCE_NOT_FOUND", f"No evidence {evidence_id}.")


@router.get("/inspection-evidence/{evidence_id}")
def inspection_evidence(
    evidence_id: str, conn: Conn = Depends(reader), config: Settings = Depends(settings)
) -> dict[str, Any]:
    card = _card(config, evidence_id)
    chip_id = card["chip"]["chip_id"] if card.get("chip") else None
    card["record_kind"] = "REAL_PUBLIC_RECORDS"
    card["reviews"] = conn.execute(
        """SELECT review_id, reviewer, outcome, visible_features, blinded_to_plume_status, supersedes, recorded_at
             FROM inspection_review_events WHERE evidence_id = %s ORDER BY recorded_at""",
        (chip_id,),
    ).fetchall()
    card["chip_url"] = f"/api/v1/inspection-evidence/{chip_id}/chip.png" if chip_id else None
    return card


@router.get("/inspection-evidence/{chip_id}/chip.png", response_class=FileResponse)
def chip(chip_id: str, config: Settings = Depends(settings)) -> FileResponse:
    if not CHIP_ID.match(chip_id):
        raise ApiError(422, "INVALID_CHIP_ID", "A chip ID looks like CHIP-0123456789ab.")
    path = resolve(config.repo_root, f"data/gold/inspection/chips/{chip_id}.png")
    if not path.is_file():
        raise ApiError(
            404,
            "RESULT_NOT_BUILT",
            f"Chip {chip_id} has not been built.",
            {"build_with": "make gate6"},
        )
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=3600"})
