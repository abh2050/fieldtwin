"""Human review of aerial evidence, kept as an append-only ledger.

A reviewer can note what an image shows, mark it unusable, or suggest field verification. There is no
outcome for confirming a leak or naming a source, because imagery and proximity can't establish either.
A corrected review is a new event that supersedes the old one. Nothing is edited or deleted.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import claims


class ReviewOutcome(StrEnum):
    NO_FEATURE_OF_NOTE = "NO_FEATURE_OF_NOTE"
    INFRASTRUCTURE_VISIBLE = "INFRASTRUCTURE_VISIBLE"
    IMAGE_UNUSABLE = "IMAGE_UNUSABLE"
    FIELD_VERIFICATION_SUGGESTED = "FIELD_VERIFICATION_SUGGESTED"


class ReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    review_id: str = Field(default_factory=lambda: uuid4().hex)
    evidence_id: str
    reviewer: str = Field(min_length=1)
    outcome: ReviewOutcome
    note: str = ""
    blinded_to_plume_status: bool
    supersedes: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provenance_class: Literal["OBSERVED"] = "OBSERVED"

    @field_validator("note")
    @classmethod
    def _note_is_supported(cls, note: str) -> str:
        # A note is the reviewer's own record, but it can't assert what the evidence can't show.
        return claims.check(note)


class ReviewError(ValueError):
    pass


class ReviewLedger:
    """Append-only JSON lines. The current finding for an item is its latest unsuperseded event."""

    def __init__(self, path: Path):
        self.path = path

    def events(self) -> list[ReviewEvent]:
        if not self.path.exists():
            return []
        return [
            ReviewEvent.model_validate_json(line)
            for line in self.path.read_text().splitlines()
            if line.strip()
        ]

    def append(self, event: ReviewEvent) -> ReviewEvent:
        existing = self.events()
        ids = {e.review_id for e in existing}
        if event.review_id in ids:
            raise ReviewError(f"review {event.review_id} already recorded")
        if event.supersedes is not None:
            target = next((e for e in existing if e.review_id == event.supersedes), None)
            if target is None:
                raise ReviewError(f"cannot supersede unknown review {event.supersedes}")
            if target.evidence_id != event.evidence_id:
                raise ReviewError("a review can only supersede a review of the same evidence")
            if any(e.supersedes == event.supersedes for e in existing):
                raise ReviewError(f"review {event.supersedes} is already superseded")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n")
        return event

    def current(self) -> dict[str, ReviewEvent]:
        events = self.events()
        superseded = {e.supersedes for e in events if e.supersedes}
        return {e.evidence_id: e for e in events if e.review_id not in superseded}

    def history(self, evidence_id: str) -> list[ReviewEvent]:
        return [e for e in self.events() if e.evidence_id == evidence_id]


def pending(evidence_ids: Iterable[str], ledger: ReviewLedger) -> list[str]:
    done = ledger.current()
    return [e for e in evidence_ids if e not in done]
