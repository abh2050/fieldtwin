"""Carbon Mapper acquisition: methane plumes, scene records, scene footprints, and plume quicklooks.

Provenance: everything written here is OBSERVED remote sensing. Nothing is linked to AETHER Field,
and no plume is attributed to any asset here. Association happens later, as proximity only.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import mapbox_vector_tile
from shapely.geometry import shape
from shapely.ops import unary_union

from pipelines.acquire.common import core
from pipelines.acquire.common.core import BatchManifest, FileEntry, Quarantine
from pipelines.acquire.common.errors import CountMismatch, SchemaDrift, SelectionOutOfBounds
from pipelines.acquire.common.transport import Http

SOURCE = "carbon_mapper"
_LOG = core.get_logger("acquire.carbon_mapper")

PLUME_REQUIRED = [
    "id", "plume_id", "gas", "geometry_json", "scene_id", "scene_timestamp", "instrument",
    "platform", "emission_auto", "emission_uncertainty_auto", "gsd", "status",
]  # fmt: skip
SCENE_REQUIRED = ["id", "name", "bounds", "timestamp", "instrument", "cloud_cover_pct"]
ASSET_FIELDS = ["plume_png", "plume_rgb_png", "plume_tif", "con_tif", "rgb_png"]

PLUME_COLUMNS = [
    "plume_uuid", "plume_id", "gas", "longitude", "latitude", "scene_id", "scene_timestamp",
    "instrument", "platform", "mission_phase", "emission_auto", "emission_uncertainty_auto",
    "emission_cmf_type", "emission_version", "hide_emission", "gsd", "sensitivity_mode",
    "off_nadir", "wind_speed_avg_auto", "wind_direction_avg_auto", "plume_quality", "status",
    "sector", "plume_bounds", "cmf_type", "collection", "processing_software", "published_at",
    "modified", "is_offshore", *(f"{a}_key" for a in ASSET_FIELDS), "quicklook_path",
]  # fmt: skip
SCENE_COLUMNS = [
    "scene_uuid", "scene_name", "timestamp", "instrument", "platform", "mission_phase",
    "cloud_cover_pct", "cloud_cover_pct_assessed", "not_cloudy", "published_plume_count",
    "gsd", "pixel_resolution", "sensitivity_mode", "off_nadir", "area_sqkm", "bounds",
    "footprint_wkt", "footprint_source", "published_at", "modified",
]  # fmt: skip


def load_config(root: Path) -> dict[str, Any]:
    return core.load_yaml(root / "config" / "sources" / "carbon_mapper.yaml")


def strip_signature(url: str | None) -> str | None:
    """Signed asset links expire. Keep the stable object path, never the signature."""
    if not url:
        return None
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _parse_time(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def plume_rejection(item: dict[str, Any], bbox: list[float], gas: str) -> str | None:
    """Why a plume record can't be accepted, or None. Records are quarantined, never repaired."""
    if not item.get("id") or not item.get("plume_id"):
        return "MISSING_IDENTIFIER"
    if item.get("gas") != gas:
        return "UNEXPECTED_GAS"
    geometry = item.get("geometry_json") or {}
    coordinates = geometry.get("coordinates") if geometry.get("type") == "Point" else None
    if not coordinates or len(coordinates) < 2:
        return "NO_POINT_GEOMETRY"
    lon, lat = _number(coordinates[0]), _number(coordinates[1])
    if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return "INVALID_COORDINATE"
    west, south, east, north = bbox
    if not (west <= lon <= east and south <= lat <= north):
        return "OUTSIDE_STUDY_AREA"
    when = _parse_time(item.get("scene_timestamp"))
    if when is None:
        return "INVALID_TIMESTAMP"
    if when > datetime.now(UTC):
        return "TIMESTAMP_IN_FUTURE"
    for field, reason in (
        ("emission_auto", "INVALID_EMISSION"),
        ("emission_uncertainty_auto", "INVALID_UNCERTAINTY"),
    ):
        if item.get(field) is not None:
            number = _number(item[field])
            if number is None or number < 0:
                return reason
    return None


def scene_rejection(item: dict[str, Any]) -> str | None:
    if not item.get("id") or not item.get("name"):
        return "MISSING_IDENTIFIER"
    if _parse_time(item.get("timestamp")) is None:
        return "INVALID_TIMESTAMP"
    try:
        bounds = json.loads(item["bounds"]) if isinstance(item["bounds"], str) else item["bounds"]
        west, south, east, north = (float(v) for v in bounds)
    except (KeyError, TypeError, ValueError):
        return "INVALID_BOUNDS"
    if not (west < east and south < north):
        return "INVALID_BOUNDS"
    cloud = _number(item.get("cloud_cover_pct"))
    if item.get("cloud_cover_pct") is not None and (cloud is None or not 0 <= cloud <= 100):
        return "INVALID_CLOUD_COVER"
    return None


def _require(items: list[dict[str, Any]], required: list[str], dataset: str) -> None:
    if items and (missing := [c for c in required if c not in items[0]]):
        raise SchemaDrift(f"{dataset} is missing contract fields: {missing}")


def fetch_pages(
    http: Http,
    url: str,
    params: dict[str, Any],
    page_size: int,
    count_key: str,
    out_dir: Path,
    pause: Callable[[], None],
) -> tuple[list[dict[str, Any]], int]:
    """Page with limit and offset, saving each raw page, then check the total against the source."""
    out_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    offset, reported = 0, None
    while True:
        page = http.get_json(url, {**params, "limit": page_size, "offset": offset})
        (out_dir / f"page_{offset:06d}.json").write_text(json.dumps(page))
        reported = page.get(count_key)
        if reported is None:
            raise SchemaDrift(f"{url} no longer reports {count_key}")
        batch = page.get("items", [])
        items.extend(batch)
        offset += len(batch)
        pause()
        if not batch or offset >= reported:
            break
    if len(items) != reported:
        raise CountMismatch(f"{url} reported {reported} records but returned {len(items)}.")
    return items, reported


def tile_range(bbox: list[float], zoom: int) -> list[tuple[int, int]]:
    """Web-Mercator tiles covering a bounding box."""
    n = 2**zoom

    def tx(lon: float) -> int:
        return int((lon + 180) / 360 * n)

    def ty(lat: float) -> int:
        return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    west, south, east, north = bbox
    return [(x, y) for x in range(tx(west), tx(east) + 1) for y in range(ty(north), ty(south) + 1)]


def tile_to_lonlat(x: int, y: int, zoom: int, px: float, py: float, extent: int) -> list[float]:
    """Tile-local coordinates (origin bottom-left, as decoded) to longitude and latitude."""
    n = 2**zoom
    lon = (x + px / extent) / n * 360 - 180
    merc_y = y + (1 - py / extent)
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * merc_y / n))))
    return [lon, lat]


def _tile_point(x: int, y: int, zoom: int, extent: int, px: float, py: float) -> list[float]:
    return tile_to_lonlat(x, y, zoom, px, py, extent)


def _map_coords(value: Any, convert: Callable[[float, float], list[float]]) -> Any:
    if value and isinstance(value[0], (int, float)):
        return convert(value[0], value[1])
    return [_map_coords(part, convert) for part in value]


def decode_footprints(
    tiles: Iterable[tuple[tuple[int, int], bytes]], zoom: int
) -> dict[str, dict[str, Any]]:
    """Merge each scene's polygon pieces across tiles. Returns WKT keyed by scene UUID."""
    pieces: dict[str, list[Any]] = {}
    names: dict[str, str] = {}
    for (x, y), body in tiles:
        layer = mapbox_vector_tile.decode(body).get("scenes")
        if not layer:
            continue
        extent = layer.get("extent", 4096)
        for feature in layer["features"]:
            uuid = feature["properties"].get("scene_uuid")
            geometry = feature["geometry"]
            if not uuid or geometry["type"] not in ("Polygon", "MultiPolygon"):
                continue
            converted = _map_coords(
                geometry["coordinates"], partial(_tile_point, x, y, zoom, extent)
            )
            polygon = shape({"type": geometry["type"], "coordinates": converted}).buffer(0)
            if not polygon.is_empty:
                pieces.setdefault(uuid, []).append(polygon)
                names[uuid] = feature["properties"].get("scene_id", "")
    return {
        uuid: {"wkt": unary_union(parts).wkt, "tile_scene_name": names[uuid]}
        for uuid, parts in pieces.items()
    }


def plume_row(item: dict[str, Any]) -> dict[str, Any]:
    lon, lat = item["geometry_json"]["coordinates"][:2]
    row = {
        "plume_uuid": item["id"],
        "longitude": lon,
        "latitude": lat,
        **{k: item.get(k) for k in PLUME_COLUMNS if k in item and k not in ("id",)},
        **{f"{a}_key": strip_signature(item.get(a)) for a in ASSET_FIELDS},
    }
    for key in ("plume_bounds", "publication_sources"):
        if isinstance(row.get(key), (list, dict)):
            row[key] = json.dumps(row[key])
    return row


def scene_row(item: dict[str, Any], footprint: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "scene_uuid": item["id"],
        "scene_name": item["name"],
        **{k: item.get(k) for k in SCENE_COLUMNS if k in item},
        "footprint_wkt": footprint["wkt"] if footprint else None,
        "footprint_source": "public_vector_tile" if footprint else None,
    }


def run(
    root: Path = core.REPO_ROOT,
    refresh: bool = False,
    http: Http | None = None,
    disk_usage: Any = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Acquire one batch and return its manifest. Any failure raises before COMPLETE is written."""
    cfg = load_config(root)
    config_sha = core.config_hash(cfg)
    if not refresh and (existing := core.find_complete(root, SOURCE, config_sha)):
        core.log(_LOG, "reusing completed batch", batch_id=existing["batch_id"])
        return {**existing, "reused": True}

    http = http or Http()
    version = datetime.now(UTC).strftime("%Y%m%d")
    batch_id = f"{SOURCE}-{version}-{config_sha[:10]}"
    if finished := core.completed_batch(root, SOURCE, batch_id):
        return {**finished, "reused": True}
    raw_dir = root / "data" / "raw" / SOURCE / version / batch_id
    bronze_dir = root / "data" / "bronze" / SOURCE / batch_id
    kwargs = {"disk_usage": disk_usage} if disk_usage else {}
    # Pages, a dozen tiles, and small PNG quicklooks: well under 200 MB.
    core.preflight_disk(root / "data", 200 * 1024 * 1024, cfg["disk_floor_bytes"], **kwargs)
    core.log(_LOG, "batch started", batch_id=batch_id)

    def pause() -> None:
        sleep(cfg["request_interval_s"])

    base, bbox = cfg["api_base"], cfg["study_area"]["bbox"]
    plume_items, plume_total = fetch_pages(
        http,
        f"{base}/{cfg['plumes']['endpoint']}",
        {"bbox": bbox, "plume_gas": cfg["plumes"]["gas"]},
        cfg["plumes"]["page_size"],
        "bbox_count",
        raw_dir / "plumes",
        pause,
    )
    scene_items, scene_total = fetch_pages(
        http,
        f"{base}/{cfg['scenes']['endpoint']}",
        {"bbox": bbox},
        cfg["scenes"]["page_size"],
        "count",
        raw_dir / "scenes",
        pause,
    )
    for name, total in (("plumes", plume_total), ("scenes", scene_total)):
        limits = cfg[name]
        if not limits["min_records"] <= total <= limits["max_records"]:
            raise SelectionOutOfBounds(
                f"{name}: {total} records, outside {limits['min_records']}-{limits['max_records']}."
            )
    _require(plume_items, PLUME_REQUIRED, "plumes")
    _require(scene_items, SCENE_REQUIRED, "scenes")

    zoom = cfg["footprints"]["zoom"]
    tiles: list[tuple[tuple[int, int], bytes]] = []
    (raw_dir / "tiles").mkdir(parents=True, exist_ok=True)
    for x, y in tile_range(bbox, zoom):
        url = f"{base}/{cfg['footprints']['tile_url'].format(z=zoom, x=x, y=y)}"
        body = http.get_bytes(url)
        (raw_dir / "tiles" / f"{zoom}_{x}_{y}.mvt").write_bytes(body)
        tiles.append(((x, y), body))
        pause()
    footprints = decode_footprints(tiles, zoom)

    quarantine = Quarantine(bronze_dir / "quarantine.jsonl")
    plumes, seen = [], set()
    for item in plume_items:
        reason = plume_rejection(item, bbox, cfg["plumes"]["gas"])
        if reason is None and item["plume_id"] in seen:
            reason = "DUPLICATE_PLUME_ID"
        if reason:
            quarantine.add("plumes", reason, item)
            continue
        seen.add(item["plume_id"])
        plumes.append(plume_row(item))
    scenes, seen = [], set()
    for item in scene_items:
        reason = scene_rejection(item)
        if reason is None and item["id"] in seen:
            reason = "DUPLICATE_SCENE_ID"
        if reason:
            quarantine.add("scenes", reason, item)
            continue
        seen.add(item["id"])
        scenes.append(scene_row(item, footprints.get(item["id"])))

    # Quicklooks are fetched by signed link from this run's own pages, newest plumes first.
    quicklook_dir = raw_dir / "quicklooks"
    quicklook_dir.mkdir(parents=True, exist_ok=True)
    signed = {i["plume_id"]: i.get(cfg["quicklooks"]["asset_field"]) for i in plume_items}
    for row in sorted(plumes, key=lambda r: (r["scene_timestamp"], r["plume_id"]), reverse=True)[
        : cfg["quicklooks"]["max_files"]
    ]:
        link = signed.get(row["plume_id"])
        if isinstance(link, str) and link:
            path = quicklook_dir / f"{row['plume_id']}.png"
            path.write_bytes(http.get_bytes(link))
            row["quicklook_path"] = core.rel(path, root)
            pause()

    files = [
        FileEntry(
            path=core.rel(path, root),
            sha256=core.sha256_file(path),
            size_bytes=path.stat().st_size,
            source_url=base,
        )
        for path in sorted(raw_dir.rglob("*"))
        if path.is_file()
    ]

    def stamp(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**r, "provenance_class": "OBSERVED", "source_batch_id": batch_id} for r in rows]

    extra = ["provenance_class", "source_batch_id"]
    core.write_string_parquet(bronze_dir / "plumes.parquet", stamp(plumes), PLUME_COLUMNS + extra)
    core.write_string_parquet(bronze_dir / "scenes.parquet", stamp(scenes), SCENE_COLUMNS + extra)
    core.freeze_tree(raw_dir)

    unmatched_tiles = sorted(set(footprints) - {s["scene_uuid"] for s in scenes})
    manifest = BatchManifest(
        batch_id=batch_id,
        source_system_id=SOURCE,
        source_version=version,
        config_sha256=config_sha,
        ingestion_timestamp=core.utc_now(),
        original_checksum=core.aggregate_checksum(files),
        source_record_count=plume_total + scene_total,
        accepted_count=len(plumes) + len(scenes),
        rejected_count=quarantine.count,
        processing_status=core.COMPLETE,
        manifest_uri=f"data/manifests/{SOURCE}/{batch_id}.json",
        license=cfg["license"],
        files=files,
        datasets={
            "plumes": {"source_records": plume_total, "accepted": len(plumes)},
            "scenes": {
                "source_records": scene_total,
                "accepted": len(scenes),
                "with_footprint": sum(1 for s in scenes if s["footprint_wkt"]),
            },
            "footprint_tiles": {
                "tiles": len(tiles),
                "zoom": zoom,
                "scenes_in_tiles": len(footprints),
                "tile_scenes_not_in_scene_list": len(unmatched_tiles),
            },
            "quicklooks": sum(1 for p in plumes if p.get("quicklook_path")),
            "quarantine_reasons": quarantine.reasons,
        },
        notes=[
            "The catalog is a live service with no version. Records reflect the retrieval date.",
            "Carbon Mapper publishes no checksums, so SHA-256 values prove only that files are "
            "unchanged since receipt.",
            "Signed asset links are stored without their signatures and expire upstream.",
            "Scene footprints come from public vector tiles, quantized to the tile grid.",
            "Emission rates are kg/h as published. The uncertainty field's statistical meaning "
            "is not stated in the API schema and is recorded as UNKNOWN.",
        ],
    )
    core.write_manifest(manifest, root)
    core.log(_LOG, "batch complete", batch_id=batch_id, plumes=len(plumes), scenes=len(scenes))
    return {**json.loads(core.manifest_path(root, SOURCE, batch_id).read_text()), "reused": False}
