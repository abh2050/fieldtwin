"""Inspection requests for fictional AETHER assets, generated from synthetic scenario events.

Requests are never generated for real registry wells. A plume near a real well is evidence for review,
not grounds to send anyone to a site operated by a real company. Requests carry no priority score;
prioritization is Gate 7.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.domain.events import PrioritizationInput

from . import claims


class InspectionType(StrEnum):
    GROUND_INSPECTION = "GROUND_INSPECTION"
    AERIAL_SURVEY = "AERIAL_SURVEY"


class RequestStatus(StrEnum):
    REQUESTED = "REQUESTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class InspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str
    asset_id: str
    affected_asset_id: str
    scenario_id: str
    scenario_run_id: str
    trigger_event_id: str
    inspection_type: InspectionType
    reason: str
    status: RequestStatus = RequestStatus.REQUESTED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provenance_class: Literal["SYNTHETIC"] = "SYNTHETIC"
    priority_score: None = None

    @field_validator("reason")
    @classmethod
    def _reason_is_supported(cls, reason: str) -> str:
        return claims.check(reason, synthetic=True)


class NotAFictionalAsset(ValueError):
    pass


def request_from_event(
    item: PrioritizationInput,
    fictional_assets: set[str],
    inspection_type: InspectionType = InspectionType.GROUND_INSPECTION,
) -> InspectionRequest:
    """One request per synthetic event. The ID is derived from the event, so reruns don't duplicate."""
    for asset in (item.asset_id, item.affected_asset_id):
        if asset not in fictional_assets:
            raise NotAFictionalAsset(f"{asset} is not a fictional AETHER asset")
    digest = hashlib.sha256(f"{item.event_id}|{inspection_type}".encode()).hexdigest()[:16]
    return InspectionRequest(
        request_id=f"INSP-{digest}",
        asset_id=item.asset_id,
        affected_asset_id=item.affected_asset_id,
        scenario_id=item.scenario_id,
        scenario_run_id=item.scenario_run_id,
        trigger_event_id=item.event_id,
        inspection_type=inspection_type,
        reason=(
            f"Synthetic scenario event {item.event_id} ({item.event_kind}) on simulated asset "
            f"{item.affected_asset_id}. Inspection requested to review simulated conditions."
        ),
    )
