"""Scenarios, stored runs, their telemetry, and replay control.

Replay moves a cursor over a run's stored output. It never simulates, so what a replay shows is
exactly what the simulator wrote when the run was built.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
import pyarrow.compute as pc
import pyarrow.parquet as pq
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ..auth import require, settings
from ..context import correlation_id
from ..db import reader, writer
from ..errors import ApiError
from ..results import resolve
from ..settings import Principal, Settings

router = APIRouter(prefix="/api/v1", tags=["scenarios"])
Conn = psycopg.Connection[dict[str, Any]]
OPERATORS = ("OPERATOR", "MAINTENANCE_SUPERVISOR")
# Telemetry columns an operator could see. Simulator truth lives in separate files and is never served.
SERIES_COLUMNS = [
    "offset_s",
    "simulated_time",
    "value",
    "unit",
    "reference",
    "quality",
    "sensor_status",
    "equipment_state",
]


def _runs(conn: Conn, scenario_id: str | None = None) -> list[dict[str, Any]]:
    return conn.execute(
        """SELECT scenario_run_id, scenario_id, case_name, target_asset_id, affected_asset_id, simulator_name,
                  simulator_version, config_sha256, output_sha256, output_uri, random_seed, sample_count,
                  sampling_interval_s, fault_onset_offset_s, provenance_class::text AS provenance_class
             FROM scenario_runs WHERE (%(s)s::text IS NULL OR scenario_id = %(s)s) ORDER BY scenario_run_id""",
        {"s": scenario_id},
    ).fetchall()


def _replay_view(row: dict[str, Any] | None, run: dict[str, Any] | None) -> dict[str, Any] | None:
    """The replay's position now. A PLAYING replay that has reached the end reports FINISHED."""
    if row is None or run is None:
        return None
    duration = int(run["sample_count"]) * int(run["sampling_interval_s"])
    position = float(row["position_s"])
    state = row["state"]
    if state == "PLAYING":
        elapsed = (datetime.now(UTC) - row["anchored_at"]).total_seconds()
        position += max(elapsed, 0.0) * float(row["speed"])
        if position >= duration:
            position, state = float(duration), "FINISHED"
    return {
        "scenario_run_id": row["scenario_run_id"],
        "state": state,
        "position_s": int(min(position, duration)),
        "duration_s": duration,
        "speed": row["speed"],
        "anchored_at": row["anchored_at"],
        "updated_by": row["updated_by"],
    }


def _replay(conn: Conn, scenario_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM scenario_replays WHERE scenario_id = %s", (scenario_id,)
    ).fetchone()
    if row is None:
        return None
    run = next(
        (r for r in _runs(conn, scenario_id) if r["scenario_run_id"] == row["scenario_run_id"]),
        None,
    )
    return _replay_view(row, run)


@router.get("/scenarios")
def scenarios(conn: Conn = Depends(reader)) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT scenario_id, scenario_name, scenario_description, target_facility_id, scenario_version,
                  random_seed, created_at FROM scenarios ORDER BY scenario_id"""
    ).fetchall()
    runs = _runs(conn)
    alarms = conn.execute(
        "SELECT scenario_id, count(*) AS n FROM detector_alarms GROUP BY scenario_id"
    ).fetchall()
    alarm_count = {a["scenario_id"]: a["n"] for a in alarms}
    for s in rows:
        s["runs"] = [r for r in runs if r["scenario_id"] == s["scenario_id"]]
        s["alarm_count"] = alarm_count.get(s["scenario_id"], 0)
        s["replay"] = _replay(conn, s["scenario_id"])
        s["provenance_class"] = "SYNTHETIC"
    return {"items": rows, "total": len(rows)}


def _run(conn: Conn, scenario_id: str, run_id: str) -> dict[str, Any]:
    run = next((r for r in _runs(conn, scenario_id) if r["scenario_run_id"] == run_id), None)
    if run is None:
        raise ApiError(404, "RUN_NOT_FOUND", f"No run {run_id} in scenario {scenario_id}.")
    return run


@router.get("/scenarios/{scenario_id}/runs/{run_id}/tags")
def run_tags(scenario_id: str, run_id: str, conn: Conn = Depends(reader)) -> dict[str, Any]:
    _run(conn, scenario_id, run_id)
    rows = conn.execute(
        """SELECT o.metric_name AS tag, o.unit_id, o.value_count, o.null_count, o.quality_flag,
                  t.fictional_asset_id AS asset_id, t.physical_quantity, t.canonical_metric
             FROM observations o LEFT JOIN sensor_tags t ON t.tag_id = o.sensor_tag_id
            WHERE o.scenario_run_id = %s AND o.observation_type = 'TELEMETRY_SERIES'
            ORDER BY o.metric_name""",
        (run_id,),
    ).fetchall()
    return {"scenario_run_id": run_id, "items": rows, "total": len(rows)}


@lru_cache(maxsize=8)
def _table(path: str, mtime_ns: int, size: int) -> Any:  # noqa: ARG001 - cache key
    return pq.read_table(path)


@router.get("/scenarios/{scenario_id}/runs/{run_id}/telemetry")
def telemetry(
    scenario_id: str,
    run_id: str,
    tag: str = Query(..., max_length=64),
    until_offset_s: int | None = Query(None, ge=0, description="stop at a replay position"),
    conn: Conn = Depends(reader),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    """One sensor's stored series, after checking the file belongs to this run."""
    run = _run(conn, scenario_id, run_id)
    stored = conn.execute(
        """SELECT value_count + null_count AS n FROM observations
            WHERE scenario_run_id = %s AND metric_name = %s AND observation_type = 'TELEMETRY_SERIES'""",
        (run_id, tag),
    ).fetchone()
    if stored is None:
        raise ApiError(404, "TAG_NOT_FOUND", f"Run {run_id} has no series {tag}.")
    path: Path = resolve(config.repo_root, run["output_uri"])
    if not path.is_file():
        raise ApiError(
            404,
            "RESULT_NOT_BUILT",
            f"{run['output_uri']} has not been built.",
            {"build_with": "make field"},
        )
    stat = path.stat()
    table = _table(str(path), stat.st_mtime_ns, stat.st_size)
    if "tag" not in table.column_names:
        raise ApiError(
            422,
            "SERIES_FORMAT_NOT_SERVED",
            "This is a Gate 3 single-segment run whose file mixes sensor readings with simulator truth; "
            "only Gate 4 network runs are served.",
        )
    rows = table.filter(pc.equal(table["tag"], tag))
    runs_in_file = set(rows["scenario_run_id"].unique().to_pylist())
    configs_in_file = set(rows["parameter_set_sha256"].unique().to_pylist())
    if (
        runs_in_file != {run_id}
        or configs_in_file != {run["config_sha256"]}
        or rows.num_rows != stored["n"]
    ):
        raise ApiError(
            409,
            "OUTPUT_DOES_NOT_MATCH_RUN",
            "The stored output file doesn't match the run recorded in the database; rebuild it.",
            {"rows_in_file": rows.num_rows, "rows_recorded": stored["n"]},
        )
    if until_offset_s is not None:
        rows = rows.filter(pc.less_equal(rows["offset_s"], until_offset_s))
    points = rows.select(SERIES_COLUMNS).to_pylist()
    return {
        "scenario_run_id": run_id,
        "tag": tag,
        "provenance_class": "SYNTHETIC",
        "source": {"path": run["output_uri"], "config_sha256": run["config_sha256"]},
        "fault_onset_offset_s": run["fault_onset_offset_s"],
        "points": points,
    }


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_run_id: str | None = Field(
        None, description="defaults to the scenario's only or first run"
    )
    speed: float = Field(600.0, gt=0, le=3600, description="simulated seconds per real second")


def _audit(
    conn: Conn, who: Principal, operation: str, target: str, before: Any, after: Any
) -> None:
    conn.execute(
        """INSERT INTO audit_events (actor_id, operation, target_id, "timestamp", correlation_id,
             before_state_reference, after_state_reference) VALUES (%s, %s, %s, now(), %s, %s, %s)""",
        (who.actor_id, operation, target, correlation_id.get(), before, after),
    )


def _locked(conn: Conn, scenario_id: str) -> dict[str, Any] | None:
    if (
        conn.execute("SELECT 1 FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
        is None
    ):
        raise ApiError(404, "SCENARIO_NOT_FOUND", f"No scenario {scenario_id}.")
    return conn.execute(
        "SELECT * FROM scenario_replays WHERE scenario_id = %s FOR UPDATE", (scenario_id,)
    ).fetchone()


@router.post("/scenarios/{scenario_id}/replay")
def replay(
    scenario_id: str,
    body: ReplayRequest | None = None,
    who: Principal = Depends(require(*OPERATORS)),
    conn: Conn = Depends(writer),
) -> dict[str, Any]:
    body = body or ReplayRequest.model_validate({})
    current = _locked(conn, scenario_id)
    runs = _runs(conn, scenario_id)
    run_id = body.scenario_run_id or (
        current["scenario_run_id"] if current else runs[0]["scenario_run_id"]
    )
    run = next((r for r in runs if r["scenario_run_id"] == run_id), None)
    if run is None:
        raise ApiError(404, "RUN_NOT_FOUND", f"No run {run_id} in scenario {scenario_id}.")
    view = _replay_view(current, run) if current and current["scenario_run_id"] == run_id else None
    if view and view["state"] == "PLAYING":
        raise ApiError(409, "ALREADY_PLAYING", "This replay is already playing.", view)
    start = 0 if view is None or view["state"] == "FINISHED" else view["position_s"]
    conn.execute(
        """INSERT INTO scenario_replays (scenario_id, scenario_run_id, state, position_s, speed, anchored_at, updated_by)
           VALUES (%s, %s, 'PLAYING', %s, %s, now(), %s)
           ON CONFLICT (scenario_id) DO UPDATE SET scenario_run_id = EXCLUDED.scenario_run_id, state = 'PLAYING',
             position_s = EXCLUDED.position_s, speed = EXCLUDED.speed, anchored_at = now(), updated_by = EXCLUDED.updated_by""",
        (scenario_id, run_id, start, body.speed, who.actor_id),
    )
    _audit(
        conn, who, "SCENARIO_REPLAY", run_id, view["state"] if view else None, f"PLAYING@{start}s"
    )
    result = _replay(conn, scenario_id)
    conn.commit()
    return {"scenario_id": scenario_id, "replay": result}


@router.post("/scenarios/{scenario_id}/pause")
def pause(
    scenario_id: str, who: Principal = Depends(require(*OPERATORS)), conn: Conn = Depends(writer)
) -> dict[str, Any]:
    current = _locked(conn, scenario_id)
    view = _replay(conn, scenario_id) if current else None
    if view is None or view["state"] != "PLAYING":
        raise ApiError(409, "NOT_PLAYING", "Only a playing replay can be paused.", view)
    conn.execute(
        """UPDATE scenario_replays SET state = 'PAUSED', position_s = %s, anchored_at = now(), updated_by = %s
            WHERE scenario_id = %s""",
        (view["position_s"], who.actor_id, scenario_id),
    )
    _audit(
        conn,
        who,
        "SCENARIO_PAUSE",
        view["scenario_run_id"],
        "PLAYING",
        f"PAUSED@{view['position_s']}s",
    )
    result = _replay(conn, scenario_id)
    conn.commit()
    return {"scenario_id": scenario_id, "replay": result}


@router.post("/scenarios/{scenario_id}/reset")
def reset(
    scenario_id: str, who: Principal = Depends(require(*OPERATORS)), conn: Conn = Depends(writer)
) -> dict[str, Any]:
    current = _locked(conn, scenario_id)
    if current is None:
        raise ApiError(409, "NO_REPLAY", "This scenario has no replay to reset.")
    before = _replay(conn, scenario_id)
    conn.execute(
        """UPDATE scenario_replays SET state = 'STOPPED', position_s = 0, anchored_at = now(), updated_by = %s
            WHERE scenario_id = %s""",
        (who.actor_id, scenario_id),
    )
    _audit(
        conn,
        who,
        "SCENARIO_RESET",
        current["scenario_run_id"],
        before["state"] if before else None,
        "STOPPED@0s",
    )
    result = _replay(conn, scenario_id)
    conn.commit()
    return {"scenario_id": scenario_id, "replay": result}
