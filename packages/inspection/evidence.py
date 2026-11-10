"""Display-ready evidence for one registry well. Every sentence passes the claim guard.

This is the view model the application renders. It carries attribution text for each source and a
fixed statement of what the evidence can't show, so a display can't drop them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import claims
from .contracts import CoverageStatus, ImageChip, ProximityLink, WellCoverage

CARBON_MAPPER_ATTRIBUTION = "Data by Carbon Mapper®. Source: Carbon Mapper (data.carbonmapper.org)"
NAIP_ATTRIBUTION = "Imagery: USDA NAIP, accessed through Microsoft Planetary Computer"

LIMITS = (
    "Spatial proximity is not source attribution.",
    "The registry lists gas wells only. Other infrastructure nearby is not represented.",
    "Plume origins are estimates and may not match infrastructure locations exactly.",
    "Aerial imagery provides context only. It carries no labels for emissions or equipment condition.",
    "Absence of a plume means only that nothing exceeded the instrument's detection limit when imaged.",
    "These are real public records. None of them describes AETHER Field, which is fictional.",
)

_STATUS_TEXT = {
    CoverageStatus.NOT_IMAGED: "No Carbon Mapper scene footprint in this batch contains this location.",
    CoverageStatus.IMAGED_CLOUDY_ONLY: "Scenes contain this location, but none was under the cloud limit.",
    CoverageStatus.IMAGED_NO_PLUME_NEARBY: (
        "Clear scenes contain this location, and no plume origin lies within the radius."
    ),
    CoverageStatus.PLUME_NEARBY: "One or more plume origins lie within the radius of this location.",
}


class PlumeNearby(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plume_id: str
    observed_at: datetime
    instrument: str
    distance_m: float
    rank_for_plume: int
    wells_within_radius_of_plume: int
    emission_kg_per_h: float | None
    emission_uncertainty_kg_per_h: float | None
    uncertainty_definition: Literal["UNKNOWN"] = "UNKNOWN"
    caption: str


class EvidenceCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_asset_id: str
    headline: str
    coverage_status: CoverageStatus
    coverage_text: str
    radius_m: float
    plumes: list[PlumeNearby]
    chip: ImageChip | None
    chip_caption: str | None
    attributions: list[str]
    limits: list[str]
    provenance: Literal["OBSERVED records with DERIVED proximity"] = (
        "OBSERVED records with DERIVED proximity"
    )

    def all_text(self) -> list[str]:
        texts = [self.headline, self.coverage_text, *self.limits]
        texts += [p.caption for p in self.plumes]
        if self.chip_caption:
            texts.append(self.chip_caption)
        return texts


def plume_caption(link: ProximityLink, instrument: str, observed_at: datetime) -> str:
    others = link.candidates_within_radius - 1
    company = (
        "no other registered well is within the radius"
        if others == 0
        else f"{others} other registered well{'s are' if others > 1 else ' is'} also within the radius"
    )
    return claims.check(
        f"Plume origin detected by {instrument} on {observed_at:%Y-%m-%d}, "
        f"{link.distance_m:.0f} m from this registered well; {company}. "
        "Spatial proximity only, not source attribution."
    )


def build_card(
    coverage: WellCoverage,
    links: Sequence[ProximityLink],
    plume_details: dict[str, dict],
    chip: ImageChip | None,
    radius_m: float,
) -> EvidenceCard:
    """Assemble the card. Raises UnsupportedClaim if any text would overstate the evidence."""
    nearby = []
    for link in sorted(links, key=lambda k: (k.distance_m, k.plume_id)):
        detail = plume_details[link.plume_id]
        nearby.append(
            PlumeNearby(
                plume_id=link.plume_id,
                observed_at=detail["observed_at"],
                instrument=detail["instrument"],
                distance_m=link.distance_m,
                rank_for_plume=link.rank,
                wells_within_radius_of_plume=link.candidates_within_radius,
                emission_kg_per_h=detail.get("emission_kg_per_h"),
                emission_uncertainty_kg_per_h=detail.get("emission_uncertainty_kg_per_h"),
                caption=plume_caption(link, detail["instrument"], detail["observed_at"]),
            )
        )
    headline = claims.check(
        f"{len(nearby)} plume origin{'s' if len(nearby) != 1 else ''} within {radius_m:.0f} m"
        if nearby
        else f"No plume origin within {radius_m:.0f} m in this batch"
    )
    chip_caption = None
    if chip is not None:
        chip_caption = claims.check(
            f"NAIP image acquired {chip.acquisition_date:%Y-%m-%d} at "
            f"{chip.ground_sample_distance_m:g} m resolution, covering this registered location. "
            "Context only."
        )
    attributions = [CARBON_MAPPER_ATTRIBUTION] + ([NAIP_ATTRIBUTION] if chip else [])
    card = EvidenceCard(
        source_asset_id=coverage.source_asset_id,
        headline=headline,
        coverage_status=coverage.status,
        coverage_text=claims.check(_STATUS_TEXT[coverage.status]),
        radius_m=radius_m,
        plumes=nearby,
        chip=chip,
        chip_caption=chip_caption,
        attributions=attributions,
        limits=[claims.check(text) for text in LIMITS],
    )
    return card
