"""Attempt control for the final splits: an append-only ledger of every generation and scoring attempt.

Each attempt writes a START event before any work and an END event when it stops, with its status,
errors, and output hashes. Events are only ever appended; no line is rewritten.

- A completed attempt of a kind (GENERATE or SCORE) for a split refuses any further attempt.
- An incomplete attempt (START with no END, or END with status FAILED) refuses a fresh attempt. It can
  only be continued by an explicit resume that names it, which is itself recorded as a new attempt.
- Output files are created exclusively and named per attempt, so nothing earlier is overwritten.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .freeze import RECORD

KINDS = ("GENERATE", "SCORE")
COMPLETED, FAILED = "COMPLETED", "FAILED"


class AttemptRefused(RuntimeError):
    """The ledger doesn't allow this attempt."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, text: str) -> str:
    """Create a file that must not exist yet, and return its SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x") as handle:
        handle.write(text)
    return sha256(path)


def events(ledger: Path) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


def _append(ledger: Path, event: dict[str, Any]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def attempts(ledger: Path, split: str, kind: str) -> list[dict[str, Any]]:
    """Attempts for one split and kind, in order, each with its START event and END event (or None)."""
    found: dict[str, dict[str, Any]] = {}
    for event in events(ledger):
        if event["split"] != split or event["kind"] != kind:
            continue
        entry = found.setdefault(event["attempt_id"], {"start": None, "end": None})
        entry["start" if event["event"] == "START" else "end"] = event
    return [{"attempt_id": k, **v} for k, v in found.items()]


def completed(ledger: Path, split: str, kind: str) -> dict[str, Any] | None:
    for attempt in attempts(ledger, split, kind):
        if attempt["end"] and attempt["end"]["status"] == COMPLETED:
            return attempt
    return None


def next_attempt_id(ledger: Path, split: str, kind: str) -> str:
    return f"{split}-{kind.lower()}-{len(attempts(ledger, split, kind)) + 1:03d}"


def begin(
    ledger: Path, split: str, kind: str, root: Path, resume_of: str | None = None
) -> dict[str, Any]:
    """Record a START event before any work, or refuse."""
    if kind not in KINDS:
        raise ValueError(kind)
    if completed(ledger, split, kind):
        raise AttemptRefused(
            f"{split} already has a completed {kind} attempt; a second one is refused"
        )
    incomplete = [
        a for a in attempts(ledger, split, kind) if not a["end"] or a["end"]["status"] != COMPLETED
    ]
    latest = incomplete[-1]["attempt_id"] if incomplete else None
    if latest and resume_of != latest:
        raise AttemptRefused(
            f"incomplete attempt {latest} exists; continue it only with an explicit resume of {latest}"
        )
    if resume_of and not latest:
        raise AttemptRefused(f"there is no incomplete attempt to resume ({resume_of})")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    ).stdout.strip()
    record = root / RECORD
    event = {
        "event": "START",
        "attempt_id": next_attempt_id(ledger, split, kind),
        "split": split,
        "kind": kind,
        "resume_of": resume_of,
        "commit": head,
        "freeze_record_sha256": sha256(record) if record.exists() else None,
        "at": _now(),
    }
    _append(ledger, event)
    return event


def end(
    ledger: Path,
    start: dict[str, Any],
    status: str,
    outputs: dict[str, str],
    errors: list[str],
    state: dict[str, Any] | None = None,
) -> None:
    _append(
        ledger,
        {
            "event": "END",
            "attempt_id": start["attempt_id"],
            "split": start["split"],
            "kind": start["kind"],
            "status": status,
            "outputs": outputs,
            "errors": errors,
            "state": state or {},
            "at": _now(),
        },
    )
