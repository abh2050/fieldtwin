"""Whether each registry well fell inside a Carbon Mapper scene, and whether any plume lay near it.

Carbon Mapper treats a scene as a candidate null detect only when cloud cover is under 25% and the
scene intersects the location. Even then, absence of a plume means only that nothing exceeded the
instrument's detection limit at that moment.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from shapely import wkt
from shapely.geometry import Point, box
from shapely.prepared import prep

from .association import Points
from .contracts import CoverageStatus, ProximityLink, WellCoverage


@dataclass(frozen=True)
class Scene:
    scene_uuid: str
    timestamp: datetime
    cloud_cover_pct: float | None
    bounds: tuple[float, float, float, float]
    footprint_wkt: str | None


def well_coverage(
    wells: Points,
    scenes: Sequence[Scene],
    links: Sequence[ProximityLink],
    max_cloud_cover_pct: float,
) -> list[WellCoverage]:
    shapes = [(s, prep(wkt.loads(s.footprint_wkt)) if s.footprint_wkt else None) for s in scenes]
    near: dict[str, int] = {}
    for link in links:
        near[link.source_asset_id] = near.get(link.source_asset_id, 0) + 1

    results = []
    for well_id, lat, lon in zip(wells.ids, wells.lat, wells.lon, strict=True):
        point = Point(float(lon), float(lat))
        inside, clear, bounds_only = [], [], 0
        for scene, footprint in shapes:
            if footprint is None:
                bounds_only += int(box(*scene.bounds).covers(point))
                continue
            if footprint.covers(point):
                inside.append(scene)
                cloud = scene.cloud_cover_pct
                if cloud is not None and cloud <= max_cloud_cover_pct:
                    clear.append(scene)
        plumes = near.get(well_id, 0)
        if plumes:
            status = CoverageStatus.PLUME_NEARBY
        elif not inside:
            status = CoverageStatus.NOT_IMAGED
        elif clear:
            status = CoverageStatus.IMAGED_NO_PLUME_NEARBY
        else:
            status = CoverageStatus.IMAGED_CLOUDY_ONLY
        times = sorted(s.timestamp for s in clear)
        results.append(
            WellCoverage(
                source_asset_id=well_id,
                scenes_in_footprint=len(inside),
                clear_scenes_in_footprint=len(clear),
                scenes_without_footprint_in_bounds=bounds_only,
                plumes_within_radius=plumes,
                first_clear_scene=times[0] if times else None,
                last_clear_scene=times[-1] if times else None,
                status=status,
            )
        )
    return results
