"""Decision storage and human review. Nothing becomes verified here without a named reviewer."""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from packages.domain.reconciliation import ReconciliationDecision


class ReviewError(ValueError):
    """A review that isn't allowed, such as approving proximity as identity."""


NEVER_APPROVABLE = {"PROXIMITY_CANDIDATE", "EMISSION_NEAR", "EXPERIMENTAL_ASSIGNMENT"}
_COLUMNS = (
    "module", "subject_type", "subject_id", "object_type", "object_id", "relationship_type",
    "method", "evidence", "confidence", "uncertainty", "verification_status", "provenance_class",
    "algorithm_version", "batch_id",
)  # fmt: skip


def store_decisions(conn: psycopg.Connection, decisions: list[ReconciliationDecision]) -> int:
    if not decisions:
        return 0
    rows = []
    for decision in decisions:
        row = decision.model_dump(mode="json")
        row["evidence"] = json.dumps(row["evidence"])
        row["uncertainty"] = None if row["uncertainty"] is None else json.dumps(row["uncertainty"])
        rows.append(row)
    marks = ", ".join(f"%({c})s" for c in _COLUMNS)
    sql = f"INSERT INTO reconciliation_decisions ({', '.join(_COLUMNS)}) VALUES ({marks})"
    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)
    return len(rows)


def review_queue(conn: psycopg.Connection, limit: int = 100) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT * FROM v_reconciliation_review_queue ORDER BY decision_id LIMIT %s", (limit,)
        )
        return cursor.fetchall()


def apply_review(
    conn: psycopg.Connection,
    decision_id: int,
    reviewer: str,
    action: str,
    rationale: str,
    evidence: dict[str, Any] | None = None,
) -> int | None:
    """Record a review and, for approve or reject, add a superseding decision.

    Returns the new decision's ID. A request for evidence changes no status and returns None.
    """
    evidence = evidence or {}
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT * FROM reconciliation_decisions WHERE decision_id = %s", (decision_id,)
        )
        decision = cursor.fetchone()
    if decision is None:
        raise ReviewError(f"decision {decision_id} doesn't exist")
    if action == "APPROVE":
        if decision["relationship_type"] in NEVER_APPROVABLE:
            raise ReviewError(
                f"{decision['relationship_type']} can't be approved as verified. "
                "Record a separate decision with evidence for a stronger relationship."
            )
        if (
            decision["relationship_type"] == "SAME_AS"
            and "authoritative_identifier" not in evidence
        ):
            raise ReviewError("approving an identity requires citing an authoritative identifier")

    row = conn.execute(
        """INSERT INTO reconciliation_reviews (decision_id, reviewer, action, rationale, evidence)
           VALUES (%s, %s, %s, %s, %s) RETURNING review_id""",
        (decision_id, reviewer, action, rationale, json.dumps(evidence)),
    ).fetchone()
    review_id = row[0] if row else None
    if action == "REQUEST_EVIDENCE":
        return None

    merged = {**decision["evidence"], **evidence, "reviewer": reviewer, "rationale": rationale}
    status = "VERIFIED" if action == "APPROVE" else "REJECTED"
    created = conn.execute(
        """INSERT INTO reconciliation_decisions (module, subject_type, subject_id, object_type, object_id,
             relationship_type, method, evidence, uncertainty, verification_status, provenance_class,
             algorithm_version, batch_id, supersedes_decision_id, review_id)
           VALUES (%s, %s, %s, %s, %s, %s, 'HUMAN_REVIEW', %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING decision_id""",
        (
            decision["module"],
            decision["subject_type"],
            decision["subject_id"],
            decision["object_type"],
            decision["object_id"],
            decision["relationship_type"],
            json.dumps(merged),
            None if decision["uncertainty"] is None else json.dumps(decision["uncertainty"]),
            status,
            decision["provenance_class"],
            decision["algorithm_version"],
            decision["batch_id"],
            decision_id,
            review_id,
        ),
    ).fetchone()
    return created[0] if created else None
