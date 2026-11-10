"""Typed records for aerial evidence. None of them can express source attribution.

A plume near a well is recorded as proximity. There is no field for "caused by", "emitted from",
or "confirmed leak", and the relationship types allowed here exclude SOURCE_ATTRIBUTED_TO.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

METHOD_VERSION = "gate6-proximity-v1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CoverageStatus(StrEnum):
    # No scene footprint contains the well.
    NOT_IMAGED = "NOT_IMAGED"
    # Only scenes over the cloud limit contain it, so absence of a plume means little.
    IMAGED_CLOUDY_ONLY = "IMAGED_CLOUDY_ONLY"
    # A clear scene contains it and no plume lies within the radius. Not a clean bill of health.
    IMAGED_NO_PLUME_NEARBY = "IMAGED_NO_PLUME_NEARBY"
    # A plume origin lies within the radius. Proximity only.
    PLUME_NEARBY = "PLUME_NEARBY"


class ProximityLink(_Strict):
    """A plume origin within a radius of a registry well. Never a statement of source."""

    plume_id: str
    source_asset_id: str
    distance_m: float = Field(ge=0)
    rank: int = Field(ge=1, description="1 is the nearest well to this plume")
    candidates_within_radius: int = Field(ge=1)
    radius_m: float = Field(gt=0)
    relationship_type: Literal["EMISSION_NEAR"] = "EMISSION_NEAR"
    verification_status: Literal["UNVERIFIED"] = "UNVERIFIED"
    confidence: None = None
    provenance_class: Literal["DERIVED"] = "DERIVED"
    method_version: str = METHOD_VERSION


class WellCoverage(_Strict):
    source_asset_id: str
    scenes_in_footprint: int = Field(ge=0)
    clear_scenes_in_footprint: int = Field(ge=0)
    scenes_without_footprint_in_bounds: int = Field(ge=0)
    plumes_within_radius: int = Field(ge=0)
    first_clear_scene: datetime | None
    last_clear_scene: datetime | None
    status: CoverageStatus
    provenance_class: Literal["DERIVED"] = "DERIVED"
    method_version: str = METHOD_VERSION


class ImageChip(_Strict):
    """A NAIP image window around a registry well. Context imagery, never a label."""

    chip_id: str
    source_asset_id: str
    stac_item_id: str
    acquisition_date: date
    ground_sample_distance_m: float = Field(gt=0)
    crs: str
    footprint_wgs84: tuple[float, float, float, float]
    source_href: str = Field(description="Asset URL without any access token")
    path: str
    sha256: str
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    bands: int = Field(gt=0)
    selection_group: Literal["NEAR_PLUME", "CONTROL"]
    relationship_type: Literal["IMAGE_COVERS"] = "IMAGE_COVERS"
    provenance_class: Literal["OBSERVED"] = "OBSERVED"
