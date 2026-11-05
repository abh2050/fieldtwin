"""Rules that decide whether a reported coordinate may enter spatial analysis. Values are never changed."""

from __future__ import annotations

import math
import re
from statistics import median
from typing import Any

from packages.domain.models import SpatialStatus

PEER_RULE = "SPATIAL-PLSS-PEER-1"
DATUM_CONFLICT_RULE = "DATUM-LABEL-CONFLICT-1"
DATUM_MISSING_RULE = "DATUM-LABEL-MISSING-1"
# A PLSS township is about 9.7 km square, so its corners are under 14 km from its center.
MAX_PEER_DISTANCE_KM = 30.0
_TOWNSHIP = re.compile(r"-(\d+[NS])-(\d+[EW])$")


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def township(ulstr: str | None) -> str | None:
    match = _TOWNSHIP.search((ulstr or "").strip())
    return f"{match[1]}-{match[2]}" if match else None


def plss_peer_outliers(wells: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Find wells far from the median location of other wells reporting the same township."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for well in wells:
        if name := township(well.get("ulstr")):
            groups.setdefault(name, []).append(well)

    outliers = {}
    for name, members in groups.items():
        for well in members:
            peers = [w for w in members if w["id"] != well["id"]]
            if len(peers) < 3:
                continue  # Too few peers to judge, so no finding is invented.
            center_lat = median(float(w["latitude"]) for w in peers)
            center_lon = median(float(w["longitude"]) for w in peers)
            distance = distance_km(
                float(well["latitude"]), float(well["longitude"]), center_lat, center_lon
            )
            if distance > MAX_PEER_DISTANCE_KM:
                outliers[well["id"]] = {
                    "township": name,
                    "distance_from_peer_median_km": round(distance, 1),
                    "peer_median_latitude": round(center_lat, 6),
                    "peer_median_longitude": round(center_lon, 6),
                    "peer_count": len(peers),
                    "threshold_km": MAX_PEER_DISTANCE_KM,
                }
    return outliers


def datum_finding(arcgis_label: str | None, ftp_label: str | None) -> str | None:
    """Return the rule a pair of datum labels breaks, or None if both name the same datum."""
    a, b = (arcgis_label or "").strip(), (ftp_label or "").strip()
    if a and a == b:
        return None
    return DATUM_MISSING_RULE if not a or not b else DATUM_CONFLICT_RULE


def spatial_status(is_outlier: bool, datum_rule: str | None) -> SpatialStatus:
    if is_outlier:
        return SpatialStatus.QUARANTINED
    return SpatialStatus.UNRESOLVED_DATUM if datum_rule else SpatialStatus.USABLE
