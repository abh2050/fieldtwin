"""Geospatial association. Proximity produces review candidates, and nothing more."""

from __future__ import annotations

import math
from dataclasses import dataclass

from packages.domain.models import ProvenanceClass, SpatialStatus
from packages.domain.reconciliation import (
    EntityType,
    Method,
    Module,
    ReconciliationDecision,
    Relationship,
    Status,
)

EARTH_RADIUS_M = 6_371_000.0
LOCATION_QUALITY = (
    "The source describes locations as approximate and publishes no numeric uncertainty."
)


@dataclass(frozen=True)
class Located:
    entity_type: EntityType
    record_id: str
    latitude: float
    longitude: float
    spatial_status: SpatialStatus = SpatialStatus.USABLE


def distance_m(a: Located, b: Located) -> float:
    p1, p2 = math.radians(a.latitude), math.radians(b.latitude)
    h = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b.longitude - a.longitude) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def proximity_decision(
    a: Located,
    b: Located,
    distance: float,
    radius_m: float,
    algorithm: str,
    relationship: Relationship = Relationship.PROXIMITY_CANDIDATE,
    batch_id: str | None = None,
    footprint_uncertainty_m: float | None = None,
) -> ReconciliationDecision:
    return ReconciliationDecision(
        module=Module.GEOSPATIAL,
        subject_type=a.entity_type,
        subject_id=a.record_id,
        object_type=b.entity_type,
        object_id=b.record_id,
        relationship_type=relationship,
        method=Method.GEOSPATIAL_PROXIMITY,
        evidence={"distance_m": round(distance, 1), "search_radius_m": radius_m},
        uncertainty={
            "location_quality": LOCATION_QUALITY,
            "footprint_uncertainty_m": footprint_uncertainty_m,
        },
        verification_status=Status.UNVERIFIED,
        provenance_class=ProvenanceClass.INFERRED,
        algorithm_version=algorithm,
        batch_id=batch_id,
    )


def candidates_near(
    subject: Located,
    others: list[Located],
    radius_m: float,
    algorithm: str,
    relationship: Relationship = Relationship.PROXIMITY_CANDIDATE,
    footprint_uncertainty_m: float = 0.0,
) -> list[ReconciliationDecision]:
    """Candidates within the radius, widened by any footprint uncertainty.

    Coordinates that are quarantined or have an unresolved datum take no part, and identical
    coordinates still yield only a candidate.
    """
    if subject.spatial_status is not SpatialStatus.USABLE:
        return []
    reach = radius_m + footprint_uncertainty_m
    decisions = []
    for other in others:
        if other.record_id == subject.record_id:
            continue
        if other.spatial_status is not SpatialStatus.USABLE:
            continue
        distance = distance_m(subject, other)
        if distance <= reach:
            decisions.append(
                proximity_decision(
                    subject,
                    other,
                    distance,
                    radius_m,
                    algorithm,
                    relationship,
                    footprint_uncertainty_m=footprint_uncertainty_m or None,
                )
            )
    return decisions
