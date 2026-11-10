"""Associate Carbon Mapper plumes and scenes with registry wells, by proximity and coverage only.

Writes data/silver/inspection/ (real per-well records, never committed) and an aggregate summary.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkt
from shapely.geometry import Point, box

from packages.inspection.association import (
    Points,
    first_of_each_group,
    location_groups,
    matched_null,
    matched_table,
    proximity_links,
    proximity_table,
    random_points,
)
from packages.inspection.coverage import Scene, well_coverage
from pipelines.acquire.common import core

from .wells import latest_batch, registry_wells, usable_points

SILVER = Path("data") / "silver" / "inspection"


def load_rules(root: Path) -> dict[str, Any]:
    return core.load_yaml(root / "config" / "inspection" / "gate6_association.yaml")


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _float(value: Any) -> float | None:
    return None if value in (None, "", "None") else float(value)


def load_carbon_mapper(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    manifest = latest_batch(root, "carbon_mapper")
    bronze = root / "data" / "bronze" / "carbon_mapper" / manifest["batch_id"]
    return (
        pd.read_parquet(bronze / "plumes.parquet"),
        pd.read_parquet(bronze / "scenes.parquet"),
        manifest,
    )


def plume_points(plumes: pd.DataFrame) -> Points:
    return Points.of(
        plumes["plume_id"].tolist(),
        plumes["latitude"].astype(float).tolist(),
        plumes["longitude"].astype(float).tolist(),
    )


def scenes_from(frame: pd.DataFrame) -> list[Scene]:
    return [
        Scene(
            scene_uuid=row["scene_uuid"],
            timestamp=_time(row["timestamp"]),
            cloud_cover_pct=_float(row["cloud_cover_pct"]),
            bounds=tuple(json.loads(row["bounds"])),
            footprint_wkt=row["footprint_wkt"] or None,
        )
        for row in frame.to_dict("records")
    ]


def run(root: Path = core.REPO_ROOT) -> dict[str, Any]:
    rules = load_rules(root)
    cm_cfg = core.load_yaml(root / "config" / "sources" / "carbon_mapper.yaml")
    wells_frame, ocd_batch = registry_wells(root)
    wells = usable_points(wells_frame)
    plumes, scenes, cm_manifest = load_carbon_mapper(root)
    points = plume_points(plumes)

    radius = float(rules["association"]["primary_radius_m"])
    links = proximity_links(points, wells, radius)
    sensitivity = {
        r: proximity_links(points, wells, float(r))
        for r in rules["association"]["sensitivity_radii_m"]
    }
    radii = [radius, *rules["association"]["sensitivity_radii_m"]]
    area = box(*cm_cfg["study_area"]["bbox"])
    footprints = {
        row["scene_uuid"]: wkt.loads(row["footprint_wkt"]).intersection(area)
        for row in scenes.to_dict("records")
        if row["footprint_wkt"]
    }
    scene_of_plume = plumes["scene_id"].tolist()
    outside = sum(
        not footprints[s].buffer(1e-4).contains(Point(lon, lat))
        for s, lat, lon in zip(scene_of_plume, points.lat, points.lon, strict=True)
    )
    matched = matched_null(
        points,
        scene_of_plume,
        footprints,
        wells,
        rules["matched_null"]["points_per_plume"],
        rules["matched_null"]["seed"],
    )
    matched_rows = matched_table(
        matched,
        radii,
        rules["matched_null"]["scene_bootstrap_resamples"],
        rules["matched_null"]["seed"],
    )
    groups = location_groups(points, rules["matched_null"]["source_group_link_m"])
    grouped = first_of_each_group(matched, groups, plumes["scene_timestamp"].tolist())
    grouped_rows = matched_table(
        grouped,
        radii,
        rules["matched_null"]["scene_bootstrap_resamples"],
        rules["matched_null"]["seed"],
    )
    reference = random_points(
        cm_cfg["study_area"]["bbox"],
        rules["geometric_reference"]["points"],
        rules["geometric_reference"]["seed"],
    )
    table = proximity_table(points, wells, reference, radii)
    coverage = well_coverage(
        wells, scenes_from(scenes), links, rules["coverage"]["max_cloud_cover_pct"]
    )

    out = root / SILVER
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([k.model_dump() for k in links]).to_parquet(out / "proximity_links.parquet")
    pd.DataFrame([c.model_dump(mode="json") for c in coverage]).to_parquet(out / "coverage.parquet")
    wells_frame.to_parquet(out / "registry_wells.parquet")

    linked_plumes = {k.plume_id for k in links}
    per_plume = pd.Series([k.candidates_within_radius for k in links if k.rank == 1])
    summary = {
        "rules_version": rules["version"],
        "inputs": {
            "nm_ocd_batch": ocd_batch,
            "carbon_mapper_batch": cm_manifest["batch_id"],
        },
        "wells": {
            "registry": len(wells_frame),
            "by_spatial_status": wells_frame["spatial_status"]
            .value_counts()
            .sort_index()
            .to_dict(),
            "used": len(wells.ids),
        },
        "plumes": len(points.ids),
        "scenes": len(scenes),
        "scenes_with_footprint": int(scenes["footprint_wkt"].notna().sum()),
        "primary_radius_m": radius,
        "links": len(links),
        "plumes_with_any_well_within_radius": len(linked_plumes),
        "wells_with_any_plume_within_radius": len({k.source_asset_id for k in links}),
        "candidate_wells_per_linked_plume": {
            "one": int((per_plume == 1).sum()),
            "two_to_four": int(((per_plume >= 2) & (per_plume <= 4)).sum()),
            "five_or_more": int((per_plume >= 5).sum()),
        },
        "sensitivity_links": {str(r): len(v) for r, v in sensitivity.items()},
        "proximity_vs_matched_null": matched_rows,
        "proximity_vs_matched_null_one_per_location_group": grouped_rows,
        "location_groups": int(groups.max() + 1),
        "plumes_outside_own_scene_footprint": int(outside),
        "scenes_with_plumes": len(set(scene_of_plume)),
        "median_footprint_share_of_study_area": round(
            float(
                pd.Series([footprints[s].area for s in set(scene_of_plume)]).median() / area.area
            ),
            3,
        ),
        "geometric_reference_uniform_box": table,
        "coverage_status": pd.Series([c.status.value for c in coverage])
        .value_counts()
        .sort_index()
        .to_dict(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
