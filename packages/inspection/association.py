"""Proximity between plume origins and registry wells, with a chance baseline.

Proximity is the only relationship computed. Carbon Mapper itself warns that plume origins may not
match infrastructure locations exactly, and the registry here holds gas wells only, so the nearest
registered well is not necessarily the nearest piece of infrastructure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import shapely

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


def sample_in_polygon(polygon, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Uniform points inside a polygon, by rejection from its bounding box. Returns (lat, lon)."""
    west, south, east, north = polygon.bounds
    lats: list[np.ndarray] = []
    lons: list[np.ndarray] = []
    have = 0
    while have < n:
        lon = rng.uniform(west, east, 4 * n)
        lat = rng.uniform(south, north, 4 * n)
        keep = shapely.contains_xy(polygon, lon, lat)
        lats.append(lat[keep])
        lons.append(lon[keep])
        have += int(keep.sum())
    return np.concatenate(lats)[:n], np.concatenate(lons)[:n]


@dataclass(frozen=True)
class MatchedNull:
    """Null points drawn inside each plume's own scene footprint, so they share its exposure."""

    plume_scene: list[str]
    plume_distance_m: np.ndarray
    null_distance_m: np.ndarray  # one row per plume, one column per null point


def matched_null(
    plumes: Points,
    scene_of_plume: Sequence[str],
    footprint_of_scene: dict[str, object],
    wells: Points,
    points_per_plume: int,
    seed: int,
) -> MatchedNull:
    """For each plume, draw points uniformly inside the footprint of the scene that observed it.

    This holds fixed where and with which instrument Carbon Mapper looked. It does not control
    for where emitting infrastructure is within a scene, so it can't say a well is a source.
    """
    rng = np.random.default_rng(seed)
    null = np.empty((len(plumes.ids), points_per_plume))
    for i, scene in enumerate(scene_of_plume):
        lat, lon = sample_in_polygon(footprint_of_scene[scene], points_per_plume, rng)
        null[i] = nearest_distance_m(Points([f"n{j}" for j in range(len(lat))], lat, lon), wells)
    return MatchedNull(list(scene_of_plume), nearest_distance_m(plumes, wells), null)


def matched_table(
    null: MatchedNull, radii: Sequence[float], resamples: int, seed: int
) -> list[dict[str, float | int]]:
    """Plume share against matched-null share at each radius, with a scene-level bootstrap.

    Plumes from one scene share conditions, so scenes are resampled, not plumes. Persistent
    sources also repeat across scenes, which this doesn't capture, so the interval is optimistic.
    """
    scenes = sorted(set(null.plume_scene))
    index = {s: np.flatnonzero(np.asarray(null.plume_scene) == s) for s in scenes}
    rng = np.random.default_rng(seed)
    draws = [
        np.concatenate([index[s] for s in rng.choice(scenes, size=len(scenes), replace=True)])
        for _ in range(resamples)
    ]
    rows = []
    for radius in sorted(radii):
        observed = (null.plume_distance_m <= radius).astype(float)
        expected = (null.null_distance_m <= radius).mean(axis=1)
        diffs = np.array([observed[d].mean() - expected[d].mean() for d in draws])
        rows.append(
            {
                "radius_m": float(radius),
                "plumes": len(observed),
                "scenes": len(scenes),
                "plume_share": float(observed.mean()),
                "matched_null_share": float(expected.mean()),
                "difference": float(observed.mean() - expected.mean()),
                "difference_low": float(np.quantile(diffs, 0.025)),
                "difference_high": float(np.quantile(diffs, 0.975)),
            }
        )
    return rows


def location_groups(points: Points, link_m: float) -> np.ndarray:
    """Group plumes whose origins chain within `link_m` of each other, as a stand-in for a
    persistent source. Returns a group label per plume. Single linkage, so groups can be long."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    near = distance_matrix(points.lat, points.lon, points.lat, points.lon) <= link_m
    return connected_components(csr_matrix(near), directed=False)[1]


def first_of_each_group(null: MatchedNull, groups: np.ndarray, order: Sequence[str]) -> MatchedNull:
    """Keep the earliest plume of each location group, so a persistent source counts once."""
    keep: dict[int, int] = {}
    for i in np.argsort(np.asarray(order), kind="stable"):
        keep.setdefault(int(groups[i]), int(i))
    rows = np.array(sorted(keep.values()))
    return MatchedNull(
        [null.plume_scene[i] for i in rows], null.plume_distance_m[rows], null.null_distance_m[rows]
    )


def proximity_table(
    plumes: Points, wells: Points, baseline: Points, radii: Sequence[float]
) -> list[dict[str, float | int]]:
    """Share of plumes and of uniform box points within each radius of any registry well.

    A geometric reference only. The box includes land no scene observed, so this does not
    compare plumes with chance.
    """
    observed = nearest_distance_m(plumes, wells)
    reference = nearest_distance_m(baseline, wells)
    rows = []
    for radius in sorted(radii):
        plume_share = float(np.mean(observed <= radius)) if len(observed) else float("nan")
        reference_share = float(np.mean(reference <= radius))
        rows.append(
            {
                "radius_m": float(radius),
                "plumes": len(observed),
                "plumes_within": int(np.sum(observed <= radius)),
                "plume_share": plume_share,
                "reference_share": reference_share,
            }
        )
    return rows
