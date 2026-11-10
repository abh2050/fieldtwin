"""Record a person's decision on a simulated work order, through the database's guarded path.

    uv run python -m pipelines.decision.decide list
    uv run python -m pipelines.decision.decide WO-... APPROVE --actor NAME --justification "..."

Decisions are recorded as `HUMAN`. The database refuses a transition the state machine doesn't allow,
a supervisor decision from another role, and a status change without its transition and audit event.
Nothing here touches equipment: work orders are records for fictional assets.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

import psycopg

from packages.decision_engine.workflow import (
    SUPERVISOR,
    SUPERVISOR_DECISIONS,
    TRANSITIONS,
    Decision,
    Status,
)
from packages.repositories.database import connect


def record_decision(
    conn: psycopg.Connection,
    external_id: str,
    decision: Decision,
    actor_id: str,
    actor_kind: str,
    actor_role: str,
    justification: str,
    at: datetime,
) -> str:
    """Insert the transition, its audit event, and any approval record, then change the status."""
    with conn.transaction():
        row = conn.execute(
            "SELECT work_order_id, status FROM work_orders WHERE external_id = %s FOR UPDATE",
            (external_id,),
        ).fetchone()
        if row is None:
            raise KeyError(external_id)
        work_order_id, status = row
        target = TRANSITIONS.get((Status(status), decision))
        if target is None:
            raise ValueError(f"{decision} is not allowed from {status}")
        sequence = conn.execute(
            "SELECT count(*) FROM work_order_transitions WHERE work_order_id = %s", (work_order_id,)
        ).fetchone()[0]  # type: ignore[index]
        transition_id = conn.execute(
            """INSERT INTO work_order_transitions (work_order_id, sequence, decision, from_status, to_status,
                 actor_id, actor_kind, actor_role, justification, decided_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING transition_id""",
            (
                work_order_id,
                sequence,
                decision.value,
                status,
                target.value,
                actor_id,
                actor_kind,
                actor_role,
                justification,
                at,
            ),
        ).fetchone()[0]  # type: ignore[index]
        conn.execute(
            """INSERT INTO audit_events (actor_id, operation, target_id, "timestamp", correlation_id,
                 before_state_reference, after_state_reference) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                actor_id,
                f"WORK_ORDER_{decision.value}",
                external_id,
                at,
                f"transition:{transition_id}",
                status,
                target.value,
            ),
        )
        if decision in SUPERVISOR_DECISIONS:
            conn.execute(
                """INSERT INTO approval_events (work_order_id, actor_id, action, justification, "timestamp",
                     actor_kind, actor_role) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    work_order_id,
                    actor_id,
                    decision.value,
                    justification,
                    at,
                    actor_kind,
                    actor_role,
                ),
            )
        conn.execute(
            "UPDATE work_orders SET status = %s WHERE work_order_id = %s",
            (target.value, work_order_id),
        )
    return target.value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("work_order", help="work order ID, or `list`")
    parser.add_argument("decision", nargs="?", choices=[d.value for d in Decision])
    parser.add_argument("--actor")
    parser.add_argument("--role", default=SUPERVISOR)
    parser.add_argument("--justification", default="")
    parser.add_argument(
        "--at",
        help="decision time on the scenario clock (ISO 8601); defaults to an hour after the latest transition",
    )
    args = parser.parse_args(argv)
    with connect() as conn:
        if args.work_order == "list":
            rows = conn.execute(
                """SELECT external_id, scenario_id, asset_id, priority_band, priority, status FROM work_orders
                    WHERE external_id IS NOT NULL ORDER BY external_id"""
            ).fetchall()
            print(
                json.dumps(
                    [
                        dict(
                            zip(
                                ["work_order", "scenario", "asset", "band", "score", "status"],
                                r,
                                strict=True,
                            )
                        )
                        for r in rows
                    ],
                    indent=2,
                )
            )
            return 0
        if not (args.decision and args.actor and args.justification.strip()):
            print("A decision needs --actor and --justification.", file=sys.stderr)
            return 2
        if args.at:
            at = datetime.fromisoformat(args.at)
        else:
            latest = conn.execute(
                """SELECT max(t.decided_at) FROM work_order_transitions t JOIN work_orders w USING (work_order_id)
                    WHERE w.external_id = %s""",
                (args.work_order,),
            ).fetchone()[0]  # type: ignore[index]
            at = (latest or datetime.now(UTC)) + timedelta(hours=1)
        try:
            status = record_decision(
                conn,
                args.work_order,
                Decision(args.decision),
                args.actor,
                "HUMAN",
                args.role,
                args.justification,
                at,
            )
        except (KeyError, ValueError, psycopg.Error) as exc:
            print(f"Not recorded: {exc}", file=sys.stderr)
            return 1
    print(f"{args.work_order} is now {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
