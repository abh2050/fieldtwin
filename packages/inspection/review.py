"""Human review of aerial evidence, kept as an append-only ledger.

A reviewer records an outcome and the features visible in an image, both from fixed vocabularies.
There is no free text, so nothing a reviewer records can assert a leak, a source, or a defect when it
is displayed. Every review is blind to plume status; the model and the database both refuse one that
isn't. A corrected review is a new event that supersedes the old one. Nothing is edited or deleted.
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


class ReviewOutcome(StrEnum):
    NO_FEATURE_OF_NOTE = "NO_FEATURE_OF_NOTE"
    INFRASTRUCTURE_VISIBLE = "INFRASTRUCTURE_VISIBLE"
    IMAGE_UNUSABLE = "IMAGE_UNUSABLE"
    FIELD_VERIFICATION_SUGGESTED = "FIELD_VERIFICATION_SUGGESTED"


class VisibleFeature(StrEnum):
    """What can be seen in an aerial photograph. None of these is a condition or an emission."""

    WELL_PAD = "WELL_PAD"
    WELLHEAD_EQUIPMENT = "WELLHEAD_EQUIPMENT"
    TANK_BATTERY = "TANK_BATTERY"
    COMPRESSION_EQUIPMENT = "COMPRESSION_EQUIPMENT"
    FLARE_STACK = "FLARE_STACK"
    PIT_OR_POND = "PIT_OR_POND"
    PIPELINE_CORRIDOR = "PIPELINE_CORRIDOR"
    OTHER_STRUCTURE = "OTHER_STRUCTURE"
    CLOUD_OR_SHADOW = "CLOUD_OR_SHADOW"
    IMAGE_ARTIFACT = "IMAGE_ARTIFACT"


class ReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    review_id: str = Field(default_factory=lambda: uuid4().hex)
    evidence_id: str
    reviewer: str = Field(min_length=1)
    outcome: ReviewOutcome
    visible_features: tuple[VisibleFeature, ...] = ()
    blinded_to_plume_status: Literal[True] = True
    supersedes: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provenance_class: Literal["OBSERVED"] = "OBSERVED"

    @field_validator("visible_features")
    @classmethod
    def _features_are_distinct(
        cls, features: tuple[VisibleFeature, ...]
    ) -> tuple[VisibleFeature, ...]:
        if len(set(features)) != len(features):
            raise ValueError("each visible feature is recorded once")
        return tuple(sorted(features))


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
