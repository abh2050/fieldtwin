"""USDA NAIP acquisition: small image windows around selected registry wells.

Provenance: chips are OBSERVED imagery. They provide context for human review and carry no labels.
Only the window around each well is read from the cloud-optimized GeoTIFF; whole tiles never
land on disk.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import rasterio
from rasterio.warp import transform, transform_bounds
from rasterio.windows import Window, from_bounds

from pipelines.acquire.common import core
from pipelines.acquire.common.core import BatchManifest, FileEntry, Quarantine
from pipelines.acquire.common.errors import CountMismatch, SchemaDrift, SourceUnavailable
from pipelines.acquire.common.transport import Http

SOURCE = "naip"
_LOG = core.get_logger("acquire.naip")
SILVER = Path("data") / "silver" / "inspection"
CHIP_COLUMNS = [
    "chip_id", "source_asset_id", "selection_group", "stac_item_id", "acquisition_date",
    "naip_year", "ground_sample_distance_m", "crs", "west", "south", "east", "north",
    "source_href", "path", "sha256", "width_px", "height_px", "bands",
]  # fmt: skip
_GDAL = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MAX_RETRY": "4"}


def load_config(root: Path) -> dict[str, Any]:
    return core.load_yaml(root / "config" / "sources" / "naip.yaml")


def chip_id(source_asset_id: str) -> str:
    """Opaque, so the review queue can't reveal whether a well was chosen for a nearby plume."""
    return "CHIP-" + hashlib.sha256(f"naip-chip|{source_asset_id}".encode()).hexdigest()[:12]


def select_wells(
    links: pd.DataFrame, coverage: pd.DataFrame, wells: pd.DataFrame, selection: dict[str, Any]
) -> pd.DataFrame:
    """Wells with the most nearby plumes, then hash-ordered controls imaged with none nearby."""
    counts = links.groupby("source_asset_id").size().rename("plumes").reset_index()
    near = counts.sort_values(["plumes", "source_asset_id"], ascending=[False, True]).head(
        selection["max_near_plume"]
    )
    clean = coverage[coverage["status"] == "IMAGED_NO_PLUME_NEARBY"]["source_asset_id"]
    seed = selection["control_seed"]
    controls = sorted(clean, key=lambda w: hashlib.sha256(f"{seed}|{w}".encode()).hexdigest())[
        : selection["controls"]
    ]
    chosen = pd.concat(
        [
            pd.DataFrame(
                {"source_asset_id": near["source_asset_id"], "selection_group": "NEAR_PLUME"}
            ),
            pd.DataFrame({"source_asset_id": controls, "selection_group": "CONTROL"}),
        ],
        ignore_index=True,
    )
    return chosen.merge(wells[["source_asset_id", "latitude", "longitude"]], on="source_asset_id")


def strip_token(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def search_items(http: Http, cfg: dict[str, Any], lon: float, lat: float) -> list[dict[str, Any]]:
    body = {
        "collections": [cfg["collection"]],
        "intersects": {"type": "Point", "coordinates": [lon, lat]},
        "limit": 50,
    }
    try:
        response = http.client.post(f"{cfg['stac_api']}/search", json=body)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"STAC search failed: {exc}") from exc
    return response.json().get("features", [])


def choose_item(items: list[dict[str, Any]], lon: float, lat: float, half_m: float) -> dict | None:
    """Latest acquisition whose image fully contains the chip window."""
    for item in sorted(items, key=lambda i: (i["properties"]["datetime"], i["id"]), reverse=True):
        epsg = item["properties"].get("proj:epsg")
        bbox = item["properties"].get("proj:bbox")
        if epsg is None or bbox is None:
            continue
        xs, ys = transform("EPSG:4326", f"EPSG:{epsg}", [lon], [lat])
        x, y = xs[0], ys[0]
        if (
            bbox[0] <= x - half_m
            and bbox[1] <= y - half_m
            and x + half_m <= bbox[2]
            and y + half_m <= bbox[3]
        ):
            return item
    return None


def read_chip(href: str, lon: float, lat: float, half_m: float, dest: Path) -> dict[str, Any]:
    with rasterio.Env(**_GDAL), rasterio.open(href) as src:
        xs, ys = transform("EPSG:4326", src.crs, [lon], [lat])
        window = from_bounds(
            xs[0] - half_m, ys[0] - half_m, xs[0] + half_m, ys[0] + half_m, transform=src.transform
        )
        window = Window(
            round(window.col_off), round(window.row_off), round(window.width), round(window.height)
        )
        data = src.read(window=window)
        if data.size == 0 or data.shape[1] < 2 or data.shape[2] < 2:
            raise SchemaDrift("NAIP window read returned no pixels")
        profile = {
            "driver": "GTiff",
            "dtype": data.dtype,
            "count": data.shape[0],
            "height": data.shape[1],
            "width": data.shape[2],
            "crs": src.crs,
            "transform": src.window_transform(window),
            "compress": "deflate",
        }
        dest.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dest, "w", **profile) as out:
            out.write(data)
            out.update_tags(SOURCE_HREF=strip_token(href), CONTENT="USDA NAIP context imagery")
        bounds = rasterio.windows.bounds(window, src.transform)
        return {
            "crs": src.crs.to_string(),
            "res": src.res[0],
            "wgs84": transform_bounds(src.crs, "EPSG:4326", *bounds),
            "shape": data.shape,
        }


def run(
    root: Path = core.REPO_ROOT,
    refresh: bool = False,
    http: Http | None = None,
    disk_usage: Any = None,
) -> dict[str, Any]:
    cfg = load_config(root)
    silver = root / SILVER
    if not (silver / "proximity_links.parquet").exists():
        raise FileNotFoundError("Run `make inspection-associate` before acquiring NAIP chips.")
    chosen = select_wells(
        pd.read_parquet(silver / "proximity_links.parquet"),
        pd.read_parquet(silver / "coverage.parquet"),
        pd.read_parquet(silver / "registry_wells.parquet"),
        cfg["selection"],
    )
    selection_sha = hashlib.sha256(
        json.dumps(chosen[["source_asset_id", "selection_group"]].values.tolist()).encode()
    ).hexdigest()
    config_sha = core.config_hash({**cfg, "selection_sha256": selection_sha})
    if not refresh and (existing := core.find_complete(root, SOURCE, config_sha)):
        return {**existing, "reused": True}

    http = http or Http()
    version = datetime.now(UTC).strftime("%Y%m%d")
    batch_id = f"{SOURCE}-{version}-{config_sha[:10]}"
    if finished := core.completed_batch(root, SOURCE, batch_id):
        return {**finished, "reused": True}
    raw_dir = root / "data" / "raw" / SOURCE / version / batch_id
    bronze_dir = root / "data" / "bronze" / SOURCE / batch_id
    kwargs = {"disk_usage": disk_usage} if disk_usage else {}
    core.preflight_disk(root / "data", 150 * 1024 * 1024, cfg["disk_floor_bytes"], **kwargs)
    core.log(_LOG, "batch started", batch_id=batch_id, wells=len(chosen))

    token = http.get_json(cfg["sas_token_url"])["token"]
    half = float(cfg["chip_half_width_m"])
    quarantine = Quarantine(bronze_dir / "quarantine.jsonl")
    rows, items_seen = [], {}
    for well in chosen.to_dict("records"):
        lon, lat = float(well["longitude"]), float(well["latitude"])
        item = choose_item(search_items(http, cfg, lon, lat), lon, lat, half)
        if item is None:
            quarantine.add("chips", "NO_SINGLE_IMAGE_CONTAINS_WINDOW", well)
            continue
        items_seen[item["id"]] = item
        href = item["assets"]["image"]["href"]
        cid = chip_id(well["source_asset_id"])
        dest = raw_dir / "chips" / f"{cid}.tif"
        info = read_chip(f"{href}?{token}", lon, lat, half, dest)
        west, south, east, north = info["wgs84"]
        rows.append(
            {
                "chip_id": cid,
                "source_asset_id": well["source_asset_id"],
                "selection_group": well["selection_group"],
                "stac_item_id": item["id"],
                "acquisition_date": item["properties"]["datetime"][:10],
                "naip_year": item["properties"].get("naip:year"),
                "ground_sample_distance_m": info["res"],
                "crs": info["crs"],
                "west": west,
                "south": south,
                "east": east,
                "north": north,
                "source_href": strip_token(href),
                "path": core.rel(dest, root),
                "sha256": core.sha256_file(dest),
                "width_px": info["shape"][2],
                "height_px": info["shape"][1],
                "bands": info["shape"][0],
            }
        )
    if not rows:
        raise CountMismatch("No NAIP chips could be read; refusing to write an empty batch.")
    (raw_dir / "stac").mkdir(parents=True, exist_ok=True)
    for item_id, item in items_seen.items():
        clean = json.loads(json.dumps(item))
        for asset in clean.get("assets", {}).values():
            asset["href"] = strip_token(asset["href"])
        (raw_dir / "stac" / f"{item_id}.json").write_text(json.dumps(clean, indent=1))

    files = [
        FileEntry(
            path=core.rel(p, root),
            sha256=core.sha256_file(p),
            size_bytes=p.stat().st_size,
            source_url=cfg["stac_api"],
        )
        for p in sorted(raw_dir.rglob("*"))
        if p.is_file()
    ]
    stamped = [{**r, "provenance_class": "OBSERVED", "source_batch_id": batch_id} for r in rows]
    core.write_string_parquet(
        bronze_dir / "chips.parquet",
        stamped,
        CHIP_COLUMNS + ["provenance_class", "source_batch_id"],
    )
    core.freeze_tree(raw_dir)
    years = sorted({str(r["naip_year"]) for r in rows})
    manifest = BatchManifest(
        batch_id=batch_id,
        source_system_id=SOURCE,
        source_version="+".join(years),
        config_sha256=config_sha,
        ingestion_timestamp=core.utc_now(),
        original_checksum=core.aggregate_checksum(files),
        source_record_count=len(chosen),
        accepted_count=len(rows),
        rejected_count=quarantine.count,
        processing_status=core.COMPLETE,
        manifest_uri=f"data/manifests/{SOURCE}/{batch_id}.json",
        license=cfg["license"],
        files=files,
        datasets={
            "chips": {
                "wells_selected": len(chosen),
                "accepted": len(rows),
                "by_group": pd.Series([r["selection_group"] for r in rows])
                .value_counts()
                .to_dict(),
                "stac_items": len(items_seen),
                "naip_years": years,
            },
            "selection_sha256": selection_sha,
            "quarantine_reasons": quarantine.reasons,
        },
        notes=[
            "Chips are windows read from cloud-optimized GeoTIFFs. Access tokens are never stored.",
            "Planetary Computer publishes no checksums for windows, so SHA-256 values prove only "
            "that chips are unchanged since they were written.",
            "Imagery is context only. It carries no emission, leak, or equipment-condition labels.",
        ],
    )
    core.write_manifest(manifest, root)
    core.log(_LOG, "batch complete", batch_id=batch_id, chips=len(rows))
    return {**json.loads(core.manifest_path(root, SOURCE, batch_id).read_text()), "reused": False}
