"""Load Gate 7 alarms, recommendations, and work orders, replaying each transition through the
database's guards: a status changes only after a valid transition and its audit event exist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg

from packages.repositories.database import REPO_ROOT, connect

from .run import GOLD

SUPERVISOR_DECISIONS = {"APPROVE", "REJECT", "REQUEST_EVIDENCE"}


def _alarm_rows(root: Path) -> list[dict[str, Any]]:
    stored = json.loads((root / GOLD / "alarms.json").read_text())["scenarios"]
    return [alarm for scenario in stored.values() for alarm in scenario["alarms"]]


def load_decisions(conn: psycopg.Connection, root: Path = REPO_ROOT) -> dict[str, int]:
    alarms = _alarm_rows(root)
    recommendations = json.loads((root / GOLD / "recommendations.json").read_text())
    orders = json.loads((root / GOLD / "work_orders.json").read_text())
    counts = {"alarms": 0, "recommendations": 0, "work_orders": 0, "transitions": 0}
    with conn.transaction():
        for a in alarms:
            inserted = conn.execute(
                """INSERT INTO detector_alarms (alarm_id, scenario_id, scenario_run_id, started_at, score, threshold,
                     model_id, model_version, model_sha256, evidence, earlier_starts_in_lookback, first_alarm_at,
                     provenance_class, input_provenance)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'INFERRED', 'SYNTHETIC')
                   ON CONFLICT DO NOTHING RETURNING 1""",
                (
                    a["alarm_id"],
                    a["scenario_id"],
                    a["scenario_run_id"],
                    a["started_at"],
                    a["score"],
                    a["threshold"],
                    a["model_id"],
                    a["model_version"],
                    a["model_sha256"],
                    json.dumps(a["evidence"]),
                    a["earlier_starts_in_lookback"],
                    a["first_alarm_at"],
                ),
            ).fetchone()
            counts["alarms"] += bool(inserted)
        for r in recommendations:
            inserted = conn.execute(
                """INSERT INTO recommendations (recommendation_id, alarm_id, scenario_id, scenario_run_id, decided_at,
                     action, candidate_assets, suppressed_assets, priority_score, priority_band, respond_within_h,
                     terms, explanation, rules_version, provenance_class)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'SYNTHETIC')
                   ON CONFLICT DO NOTHING RETURNING 1""",
                (
                    r["recommendation_id"],
                    r["alarm_id"],
                    r["scenario_id"],
                    r["scenario_run_id"],
                    r["decided_at"],
                    r["action"],
                    r["candidate_assets"],
                    r["suppressed_assets"],
                    r["priority_score"],
                    r["priority_band"],
                    r["respond_within_h"],
                    json.dumps(r["terms"]),
                    json.dumps(r["explanation"]),
                    r["rules_version"],
                ),
            ).fetchone()
            counts["recommendations"] += bool(inserted)
        for o in orders:
            if conn.execute(
                "SELECT 1 FROM work_orders WHERE external_id = %s", (o["work_order_id"],)
            ).fetchone():
                continue
            work_order_id = conn.execute(
                """INSERT INTO work_orders (scenario_id, asset_id, recommended_action, severity, priority, status,
                     evidence_reference, external_id, recommendation_id, priority_band, created_at)
                   VALUES (%s, %s, %s, %s, %s, 'RECOMMENDED', %s, %s, %s, %s, %s) RETURNING work_order_id""",
                (
                    o["scenario_id"],
                    o["asset_id"],
                    o["action"],
                    o["priority_band"],
                    o["priority_score"],
                    o["recommendation_id"],
                    o["work_order_id"],
                    o["recommendation_id"],
                    o["priority_band"],
                    o["history"][0]["at"],
                ),
            ).fetchone()[0]  # type: ignore[index]
            counts["work_orders"] += 1
            for event in o["history"]:
                transition_id = conn.execute(
                    """INSERT INTO work_order_transitions (work_order_id, sequence, decision, from_status, to_status,
                         actor_id, actor_kind, actor_role, justification, decided_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING transition_id""",
                    (
                        work_order_id,
                        event["sequence"],
                        event["decision"],
                        event["before"],
                        event["after"],
                        event["actor"]["actor_id"],
                        event["actor"]["kind"],
                        event["actor"]["role"],
                        event["justification"],
                        event["at"],
                    ),
                ).fetchone()[0]  # type: ignore[index]
                conn.execute(
                    """INSERT INTO audit_events (actor_id, operation, target_id, "timestamp", correlation_id,
                         before_state_reference, after_state_reference)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        event["actor"]["actor_id"],
                        f"WORK_ORDER_{event['decision']}",
                        o["work_order_id"],
                        event["at"],
                        f"transition:{transition_id}",
                        event["before"],
                        event["after"],
                    ),
                )
                if event["decision"] in SUPERVISOR_DECISIONS:
                    conn.execute(
                        """INSERT INTO approval_events (work_order_id, actor_id, action, justification, "timestamp",
                             actor_kind, actor_role) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (
                            work_order_id,
                            event["actor"]["actor_id"],
                            event["decision"],
                            event["justification"],
                            event["at"],
                            event["actor"]["kind"],
                            event["actor"]["role"],
                        ),
                    )
                if event["before"] is not None:
                    conn.execute(
                        "UPDATE work_orders SET status = %s WHERE work_order_id = %s",
                        (event["after"], work_order_id),
                    )
                counts["transitions"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    with connect() as conn:
        print(json.dumps(load_decisions(conn, args.root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
