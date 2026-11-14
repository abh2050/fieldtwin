"""Detector alarms (Gate 5's selected detector on simulated runs) and model evaluations."""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends

from ..auth import settings
from ..db import reader
from ..errors import ApiError
from ..pagination import PageParams, page, page_params
from ..results import read_json
from ..settings import Settings

router = APIRouter(prefix="/api/v1", tags=["anomalies"])
Conn = psycopg.Connection[dict[str, Any]]

ALARM_COLUMNS = """a.alarm_id, a.scenario_id, a.scenario_run_id, a.started_at, a.first_alarm_at, a.score, a.threshold,
  a.model_id, a.model_version, a.model_sha256, a.earlier_starts_in_lookback,
  a.provenance_class::text AS provenance_class, a.input_provenance::text AS input_provenance"""


@router.get("/anomalies")
def anomalies(
    scenario_id: str | None = None,
    params: PageParams = Depends(page_params),
    conn: Conn = Depends(reader),
) -> dict[str, Any]:
    rows = conn.execute(
        f"""SELECT {ALARM_COLUMNS}, r.recommendation_id, r.action, r.priority_band, count(*) OVER () AS _total
              FROM detector_alarms a LEFT JOIN recommendations r USING (alarm_id)
             WHERE (%(s)s::text IS NULL OR a.scenario_id = %(s)s)
             ORDER BY a.started_at LIMIT %(l)s OFFSET %(o)s""",
        {"s": scenario_id, "l": params.limit, "o": params.offset},
    ).fetchall()
    total = rows[0]["_total"] if rows else 0
    for r in rows:
        del r["_total"]
    return {
        "note": "A detector score is not a failure probability. Alarms are INFERRED from SYNTHETIC telemetry.",
        **page(rows, total, params),
    }


@router.get("/anomalies/{event_id}")
def anomaly(event_id: str, conn: Conn = Depends(reader)) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {ALARM_COLUMNS}, a.evidence FROM detector_alarms a WHERE a.alarm_id = %s",
        (event_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "ANOMALY_NOT_FOUND", f"No alarm {event_id}.")
    row["recommendations"] = conn.execute(
        """SELECT recommendation_id, action, priority_band, priority_score, respond_within_h, candidate_assets,
                  suppressed_assets, terms, explanation, rules_version, decided_at
             FROM recommendations WHERE alarm_id = %s""",
        (event_id,),
    ).fetchall()
    return row


def _method_rows(methods: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for name, m in methods.items():
        s = m.get("summary", {})
        iv = m.get("interval", {})
        out.append(
            {
                "method": name,
                "event_recall": s.get("event_recall"),
                "event_recall_interval": iv.get("event_recall"),
                "chance_event_recall": s.get("chance_event_recall"),
                "event_skill": s.get("event_skill"),
                "event_skill_interval": iv.get("event_skill"),
                "precision": s.get("precision"),
                "false_alarms_per_hour": s.get("false_alarms_per_hour"),
                "average_precision": m.get("average_precision"),
                "by_category": m.get("by_category"),
            }
        )
    return out


@router.get("/model-evaluations")
def model_evaluations(config: Settings = Depends(settings)) -> dict[str, Any]:
    """Gate 5 detection results, in-regime and held-out, as recorded. Nothing is recomputed."""
    in_regime, in_source = read_json(
        config.repo_root,
        "reports/experiments/results/aether_in_regime.json",
        "make gate5-development",
    )
    held_out, held_source = read_json(
        config.repo_root, "reports/experiments/results/aether_held_out.json", "make gate5-holdout"
    )
    regimes = {
        name: {
            method: {
                k: (r.get("summary", {}).get(k))
                for k in ("event_recall", "event_skill", "false_alarms_per_hour")
            }
            for method, r in regime.items()
            if isinstance(r, dict) and "summary" in r
        }
        for name, regime in held_out.get("regimes", {}).items()
    }
    try:
        performance, performance_source = read_json(
            config.repo_root,
            "reports/experiments/results/inference_performance.json",
            "make gate5-performance",
        )
        compute: dict[str, Any] | None = {
            "hardware": performance.get("hardware"),
            "rows": performance.get("rows", []),
            "source": performance_source,
        }
    except ApiError:
        compute = None
    dataset = in_regime.get("dataset", {})
    return {
        "reproducibility": {
            "git_sha": in_regime.get("git_sha"),
            "hardware": in_regime.get("hardware"),
            "dataset_sha256": dataset.get("dataset_sha256"),
            "parameter_sets_sha256": dataset.get("parameter_sets_sha256"),
            "cases": dataset.get("cases"),
        },
        "compute": compute,
        "track": in_regime.get("track"),
        "selected_method": in_regime.get("selection", {}).get("preferred"),
        "selection_reason": in_regime.get("selection", {}).get("reason"),
        "in_regime": {"source": in_source, "methods": _method_rows(in_regime.get("methods", {}))},
        "held_out": {
            "source": held_source,
            "pooled": _method_rows(held_out.get("pooled", {})),
            "regimes": regimes,
        },
        "report": "reports/experiments/aether_synthetic_benchmark.md",
    }
