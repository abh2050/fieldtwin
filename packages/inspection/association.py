"""Proximity between plume origins and registry wells, with a chance baseline.

Proximity is the only relationship computed. Carbon Mapper itself warns that plume origins may not
match infrastructure locations exactly, and the registry here holds gas wells only, so the nearest
registered well is not necessarily the nearest piece of infrastructure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .contracts import ProximityLink
from .geodesy import distance_matrix


@dataclass(frozen=True)
class Points:
    ids: list[str]
    lat: np.ndarray
    lon: np.ndarray

    @classmethod
    def of(cls, ids: Sequence[str], lat: Sequence[float], lon: Sequence[float]) -> Points:
        if not (len(ids) == len(lat) == len(lon)):
            raise ValueError("ids, lat and lon must have the same length")
        if len(set(ids)) != len(ids):
            raise ValueError("point identifiers must be unique")
        return cls(list(ids), np.asarray(lat, dtype=float), np.asarray(lon, dtype=float))


def nearest_distance_m(points: Points, wells: Points) -> np.ndarray:
    if not len(wells.ids):
        return np.full(len(points.ids), np.inf)
    return distance_matrix(points.lat, points.lon, wells.lat, wells.lon).min(axis=1)


def proximity_links(plumes: Points, wells: Points, radius_m: float) -> list[ProximityLink]:
    """Every well within the radius of each plume, ranked by distance. Ties break by well ID."""
    if radius_m <= 0:
        raise ValueError("radius must be positive")
    if not len(plumes.ids) or not len(wells.ids):
        return []
    distances = distance_matrix(plumes.lat, plumes.lon, wells.lat, wells.lon)
    links = []
    for row, plume_id in enumerate(plumes.ids):
        inside = np.flatnonzero(distances[row] <= radius_m)
        ordered = sorted(inside, key=lambda c: (distances[row, c], wells.ids[c]))
        for rank, column in enumerate(ordered, start=1):
            links.append(
                ProximityLink(
                    plume_id=plume_id,
                    source_asset_id=wells.ids[column],
                    distance_m=round(float(distances[row, column]), 1),
                    rank=rank,
                    candidates_within_radius=len(ordered),
                    radius_m=radius_m,
                )
            )
    return links


def random_points(bbox: Sequence[float], n: int, seed: int) -> Points:
    """Uniform in latitude and longitude. Over a box this small the area distortion is under 0.2%."""
    west, south, east, north = bbox
    rng = np.random.default_rng(seed)
    lat = rng.uniform(south, north, n)
    lon = rng.uniform(west, east, n)
    return Points([f"random-{i}" for i in range(n)], lat, lon)


def proximity_table(
    plumes: Points, wells: Points, baseline: Points, radii: Sequence[float]
) -> list[dict[str, float | int]]:
    """Share of plumes and of random points within each radius of any registry well."""
    observed = nearest_distance_m(plumes, wells)
    chance = nearest_distance_m(baseline, wells)
    rows = []
    for radius in sorted(radii):
        plume_share = float(np.mean(observed <= radius)) if len(observed) else float("nan")
        chance_share = float(np.mean(chance <= radius))
        rows.append(
            {
                "radius_m": float(radius),
                "plumes": len(observed),
                "plumes_within": int(np.sum(observed <= radius)),
                "plume_share": plume_share,
                "chance_share": chance_share,
                "share_above_chance": plume_share - chance_share,
            }
        )
    return rows
