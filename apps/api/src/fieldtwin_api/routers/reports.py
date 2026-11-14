"""Modeled economics, the audit log, and the committed experiment reports, served as recorded."""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends

from ..auth import settings
from ..db import reader
from ..errors import ApiError
from ..pagination import PageParams, page, page_params
from ..results import read_json, read_text
from ..settings import Settings

router = APIRouter(prefix="/api/v1", tags=["reports"])
Conn = psycopg.Connection[dict[str, Any]]

# The reports the Experiment Reports screen lists, with what each found. Outcomes are quoted from the
# reports themselves; the screen links to the full text.
CATALOG: list[dict[str, str]] = [
    {
        "slug": "detection",
        "gate": "Gate 5",
        "title": "Detection on the synthetic AETHER benchmark",
        "path": "reports/experiments/aether_synthetic_benchmark.md",
        "outcome": "WEAK",
        "build": "make gate5-development gate5-holdout gate5-reports",
    },
    {
        "slug": "model-comparison",
        "gate": "Gate 5",
        "title": "Model comparison",
        "path": "reports/experiments/model_comparison.md",
        "outcome": "RECORDED",
        "build": "make gate5-reports",
    },
    {
        "slug": "3w-benchmark",
        "gate": "Gate 5",
        "title": "Petrobras 3W benchmark (real labelled events)",
        "path": "reports/experiments/3w_benchmark.md",
        "outcome": "RECORDED",
        "build": "make gate5-reports",
    },
    {
        "slug": "robustness",
        "gate": "Gate 5",
        "title": "Robustness under stress",
        "path": "reports/experiments/robustness.md",
        "outcome": "RECORDED",
        "build": "make gate5-reports",
    },
    {
        "slug": "inference",
        "gate": "Gate 5",
        "title": "Inference performance",
        "path": "reports/experiments/inference_performance.md",
        "outcome": "RECORDED",
        "build": "make gate5-reports",
    },
    {
        "slug": "aerial",
        "gate": "Gate 6",
        "title": "Aerial evidence: spatial association",
        "path": "reports/inspection/spatial_association.md",
        "outcome": "PROXIMITY_ONLY",
        "build": "make gate6",
    },
    {
        "slug": "decision-engine",
        "gate": "Gate 7",
        "title": "Decision engine",
        "path": "reports/decision/decision_engine.md",
        "outcome": "RECORDED",
        "build": "make decision-reports",
    },
    {
        "slug": "economics",
        "gate": "Gate 7",
        "title": "Scheduling economics (modeled)",
        "path": "reports/economics/scheduling_comparison.md",
        "outcome": "RISK_BASED_LOST",
        "build": "make decision-reports",
    },
    {
        "slug": "d1",
        "gate": "D1",
        "title": "Gathering-line restriction diagnosis",
        "path": "reports/diagnostics/final_report.md",
        "outcome": "NOT_MET",
        "build": "committed final result",
    },
]


@router.get("/economics/comparison")
def economics(config: Settings = Depends(settings)) -> dict[str, Any]:
    data, source = read_json(
        config.repo_root, "reports/decision/results/economics.json", "make decision-economics"
    )
    policies = {}
    for name, s in data["summary"].items():
        policies[name] = {k: s[k] for k in s if isinstance(s[k], dict) and "mean" in s[k]}
    return {
        "label": data["label"],
        "horizon_days": data["horizon_days"],
        "replicates": data["replicates"],
        "seed": data["seed"],
        "economics_version": data["economics_version"],
        "rules_version": data["rules_version"],
        "detector": data["detector"],
        "policies": policies,
        "sensitivity": data["sensitivity"],
        "source": source,
        "report": "reports/economics/scheduling_comparison.md",
    }


@router.get("/audit-events")
def audit_events(
    actor_id: str | None = None,
    operation: str | None = None,
    target_id: str | None = None,
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT e.event_id, e.actor_id, e.operation, e.target_id, e."timestamp", e.correlation_id,
                  e.before_state_reference, e.after_state_reference, t.actor_kind, count(*) OVER () AS _total
             FROM audit_events e
             LEFT JOIN work_order_transitions t
               ON e.correlation_id LIKE 'transition:%%' AND t.transition_id::text = split_part(e.correlation_id, ':', 2)
            WHERE (%(a)s::text IS NULL OR e.actor_id = %(a)s) AND (%(op)s::text IS NULL OR e.operation = %(op)s)
              AND (%(t)s::text IS NULL OR e.target_id = %(t)s)
            ORDER BY e.event_id DESC LIMIT %(l)s OFFSET %(o)s""",
        {"a": actor_id, "op": operation, "t": target_id, "l": params.limit, "o": params.offset},
    ).fetchall()
    total = rows[0]["_total"] if rows else 0
    for r in rows:
        del r["_total"]
    return page(rows, total, params)


@router.get("/reports")
def reports(config: Settings = Depends(settings)) -> dict[str, Any]:
    items = [{**r, "available": (config.repo_root / r["path"]).is_file()} for r in CATALOG]
    return {"items": items, "total": len(items)}


@router.get("/reports/{slug}")
def report(slug: str, config: Settings = Depends(settings)) -> dict[str, Any]:
    entry = next((r for r in CATALOG if r["slug"] == slug), None)
    if entry is None:
        raise ApiError(404, "REPORT_NOT_FOUND", f"No report {slug}.")
    text, source = read_text(config.repo_root, entry["path"], entry["build"])
    return {**entry, "markdown": text, "source": source}


@router.get("/diagnostics/d1")
def d1(config: Settings = Depends(settings)) -> dict[str, Any]:
    outcome, source = read_json(
        config.repo_root,
        "reports/diagnostics/final/outcome-final_in_regime-score-001-final_held_out-score-001.json",
        "committed final result",
    )
    in_regime, in_source = read_json(
        config.repo_root,
        "reports/diagnostics/final/final_in_regime-score-001.json",
        "committed final result",
    )
    held_out, held_source = read_json(
        config.repo_root,
        "reports/diagnostics/final/final_held_out-score-001.json",
        "committed final result",
    )
    return {
        "outcome": outcome,
        "in_regime": in_regime,
        "held_out": held_out,
        "sources": [source, in_source, held_source],
        "report": "reports/diagnostics/final_report.md",
        "note": "SYNTHETIC cases on an uncalibrated fictional model. Not evidence about a real field.",
    }


@router.get("/overview")
def overview(conn: Conn = Depends(reader), config: Settings = Depends(settings)) -> dict[str, Any]:
    """Counts for the Overview screen, each from a query or a committed result file."""
    counts = conn.execute(
        """SELECT (SELECT count(*) FROM assets) AS fictional_assets,
                  (SELECT count(*) FROM scenarios) AS scenarios,
                  (SELECT count(*) FROM scenario_runs) AS scenario_runs,
                  (SELECT count(*) FROM detector_alarms) AS alarms,
                  (SELECT count(*) FROM recommendations WHERE action IN ('FIELD_INSPECTION', 'CHECK_INSTRUMENTATION')) AS dispatching_recommendations,
                  (SELECT count(*) FROM inspection_requests WHERE status = 'REQUESTED') AS pending_inspections,
                  (SELECT count(*) FROM data_quality_exceptions WHERE status = 'OPEN') AS open_quality_exceptions,
                  (SELECT count(*) FROM source_systems WHERE NOT is_project_generated) AS real_sources"""
    ).fetchone()
    backlog = conn.execute(
        "SELECT status, count(*) AS n FROM work_orders WHERE external_id IS NOT NULL GROUP BY status ORDER BY status"
    ).fetchall()
    kinds = conn.execute(
        """SELECT actor_kind, count(*) AS n FROM work_order_transitions WHERE decision <> 'CREATE'
            GROUP BY actor_kind ORDER BY actor_kind"""
    ).fetchall()
    economics_summary: dict[str, Any] | None
    try:
        data, source = read_json(
            config.repo_root, "reports/decision/results/economics.json", "make decision-economics"
        )
        economics_summary = {
            "label": data["label"],
            "mean_total": {k: v["total"]["mean"] for k, v in data["summary"].items()},
            "source": source,
        }
    except ApiError:
        economics_summary = None
    detection: dict[str, Any] | None
    try:
        held, held_source = read_json(
            config.repo_root,
            "reports/experiments/results/aether_held_out.json",
            "make gate5-holdout",
        )
        chosen = held["preferred_from_in_regime"]["preferred"]
        s = held["pooled"][chosen]["summary"]
        detection = {
            "method": chosen,
            "events_detected": s["events_detected"],
            "events": s["events"],
            "event_recall": s["event_recall"],
            "chance_event_recall": s["chance_event_recall"],
            "source": held_source,
        }
    except (ApiError, KeyError):
        detection = None
    try:
        outcome, _ = read_json(
            config.repo_root,
            "reports/diagnostics/final/outcome-final_in_regime-score-001-final_held_out-score-001.json",
            "committed final result",
        )
        d1_outcome = outcome["outcome"]
    except ApiError:
        d1_outcome = None
    return {
        "counts": counts,
        "work_order_backlog": backlog,
        "decisions_by_actor_kind": kinds,
        "economics": economics_summary,
        "detection": detection,
        "d1_outcome": d1_outcome,
    }
