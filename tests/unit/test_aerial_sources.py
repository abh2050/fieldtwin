"""Carbon Mapper and NAIP adapters, on records cut from the real downloads (data/fixtures)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest
import rasterio
from rasterio.warp import transform

from pipelines.acquire.carbon_mapper import adapter as cm
from pipelines.acquire.common.errors import CountMismatch, SchemaDrift
from pipelines.acquire.naip import adapter as naip

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures"
BBOX = [-104.155, 32.149, -104.012, 32.360]


def page(name: str) -> dict:
    return json.loads((FIXTURES / "carbon_mapper" / f"{name}_page.json").read_text())


class PagedHttp:
    """Serves one real page per request, as the API does, and records what was asked."""

    def __init__(self, pages: list[dict]):
        self.pages, self.calls = pages, []

    def get_json(self, url, params=None):
        self.calls.append(params)
        return self.pages[len(self.calls) - 1]


def test_real_plumes_pass_validation_and_keep_withheld_emissions_empty():
    items = page("plumes")["items"]
    assert [cm.plume_rejection(i, BBOX, "CH4") for i in items] == [None] * len(items)
    withheld = [i for i in items if i["hide_emission"]]
    assert withheld and all(cm.plume_row(i)["emission_auto"] is None for i in withheld)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"gas": "CO2"}, "UNEXPECTED_GAS"),
        ({"geometry_json": {"type": "Polygon", "coordinates": []}}, "NO_POINT_GEOMETRY"),
        ({"geometry_json": {"type": "Point", "coordinates": [-105.5, 32.2]}}, "OUTSIDE_STUDY_AREA"),
        ({"scene_timestamp": "yesterday"}, "INVALID_TIMESTAMP"),
        ({"scene_timestamp": "2999-01-01T00:00:00Z"}, "TIMESTAMP_IN_FUTURE"),
        ({"emission_auto": -1.0}, "INVALID_EMISSION"),
        ({"emission_uncertainty_auto": "n/a"}, "INVALID_UNCERTAINTY"),
        ({"plume_id": ""}, "MISSING_IDENTIFIER"),
    ],
)
def test_broken_plumes_are_quarantined_not_repaired(change, reason):
    item = {**page("plumes")["items"][1], **change}
    assert cm.plume_rejection(item, BBOX, "CH4") == reason


def test_real_scenes_pass_and_bad_bounds_fail():
    items = page("scenes")["items"]
    assert [cm.scene_rejection(i) for i in items] == [None] * len(items)
    assert cm.scene_rejection({**items[0], "bounds": "[1, 2, 0, 3]"}) == "INVALID_BOUNDS"
    assert cm.scene_rejection({**items[0], "cloud_cover_pct": "140"}) == "INVALID_CLOUD_COVER"


def test_signed_links_lose_their_signature():
    url = "https://catalog.example/a/b.png?c=1&Expires=2&Signature=abc&Key-Pair-Id=K"
    assert cm.strip_signature(url) == "https://catalog.example/a/b.png"
    assert all("Signature" not in json.dumps(i) for i in page("plumes")["items"])


def test_paging_checks_the_total_and_saves_every_page(tmp_path):
    real = page("plumes")
    first = {**real, "bbox_count": 7, "items": real["items"][:4]}
    second = {**real, "bbox_count": 7, "items": real["items"][4:5]}
    with pytest.raises(CountMismatch):
        cm.fetch_pages(
            PagedHttp([first, second, {**real, "bbox_count": 7, "items": []}]),
            "u",
            {},
            4,
            "bbox_count",
            tmp_path,
            lambda: None,
        )
    assert len(list(tmp_path.glob("page_*.json"))) == 3
    exact = {**real, "bbox_count": 5}
    items, total = cm.fetch_pages(
        PagedHttp([exact]), "u", {}, 100, "bbox_count", tmp_path / "b", lambda: None
    )
    assert total == 5 and len(items) == 5


def test_missing_count_or_fields_is_schema_drift(tmp_path):
    real = page("scenes")
    with pytest.raises(SchemaDrift):
        cm.fetch_pages(
            PagedHttp([{"items": real["items"]}]), "u", {}, 100, "count", tmp_path, lambda: None
        )
    broken = [{k: v for k, v in real["items"][0].items() if k != "bounds"}]
    with pytest.raises(SchemaDrift):
        cm._require(broken, cm.SCENE_REQUIRED, "scenes")


def test_tile_footprints_decode_inside_their_tile():
    path = sorted((FIXTURES / "carbon_mapper").glob("*.mvt"))[0]
    zoom, x, y = (int(v) for v in path.stem.split("_"))
    footprints = cm.decode_footprints([((x, y), path.read_bytes())], zoom)
    assert footprints
    west, north = cm.tile_to_lonlat(x, y, zoom, 0, 4096, 4096)
    east, south = cm.tile_to_lonlat(x, y, zoom, 4096, 0, 4096)
    from shapely import wkt

    for item in footprints.values():
        w, s, e, n = wkt.loads(item["wkt"]).bounds
        # Vector tiles keep a small buffer beyond the tile edge.
        pad = (east - west) * 0.1
        assert west - pad <= w and e <= east + pad and south - pad <= s and n <= north + pad


def test_tile_range_covers_the_study_area():
    tiles = cm.tile_range(BBOX, 12)
    assert len(tiles) == 12 and (862, 1658) in tiles
    lon, lat = cm.tile_to_lonlat(862, 1658, 12, 0, 4096, 4096)
    assert lon == pytest.approx(360 * 862 / 4096 - 180)
    assert -90 < lat < 90 and not math.isnan(lat)


# NAIP


def test_chip_ids_are_opaque_and_stable():
    a = naip.chip_id("nm_ocd:well:30-015-1")
    assert a == naip.chip_id("nm_ocd:well:30-015-1") and a != naip.chip_id("nm_ocd:well:30-015-2")
    assert "30-015" not in a and a.startswith("CHIP-")


def test_selection_takes_most_plumes_first_then_hashed_controls():
    links = pd.DataFrame({"source_asset_id": ["w1", "w2", "w2", "w3", "w3", "w3"]})
    coverage = pd.DataFrame(
        {
            "source_asset_id": ["w1", "w2", "w3", "c1", "c2", "c3", "x"],
            "status": ["PLUME_NEARBY"] * 3 + ["IMAGED_NO_PLUME_NEARBY"] * 3 + ["NOT_IMAGED"],
        }
    )
    wells = pd.DataFrame(
        {
            "source_asset_id": ["w1", "w2", "w3", "c1", "c2", "c3", "x"],
            "latitude": [32.2] * 7,
            "longitude": [-104.1] * 7,
        }
    )
    chosen = naip.select_wells(
        links, coverage, wells, {"max_near_plume": 2, "controls": 2, "control_seed": "s"}
    )
    near = chosen[chosen.selection_group == "NEAR_PLUME"].source_asset_id.tolist()
    controls = chosen[chosen.selection_group == "CONTROL"].source_asset_id.tolist()
    assert near == ["w3", "w2"]
    assert len(controls) == 2 and set(controls) <= {"c1", "c2", "c3"}
    again = naip.select_wells(
        links, coverage, wells, {"max_near_plume": 2, "controls": 2, "control_seed": "s"}
    )
    assert again.equals(chosen)


def test_item_must_contain_the_whole_window():
    item = json.loads((FIXTURES / "naip" / "stac_item.json").read_text())
    west, south, east, north = item["properties"]["proj:bbox"]
    epsg = item["properties"]["proj:epsg"]
    lons, lats = transform(
        f"EPSG:{epsg}", "EPSG:4326", [(west + east) / 2, west + 50], [(south + north) / 2] * 2
    )
    assert naip.choose_item([item], lons[0], lats[0], 150)["id"] == item["id"]
    assert naip.choose_item([item], lons[1], lats[1], 150) is None
    assert "?" not in item["assets"]["image"]["href"]


LOCAL_CHIP = FIXTURES.parent / "fixtures_local" / "naip" / "chip.tif"


@pytest.mark.skipif(
    not LOCAL_CHIP.exists(), reason="NAIP pixels are not committed; run `make fixtures`"
)
def test_window_read_keeps_crs_and_pixels(tmp_path):
    source = LOCAL_CHIP
    with rasterio.open(source) as src:
        x, y = src.xy(src.height // 2, src.width // 2)
        crs = src.crs
    lon, lat = transform(crs, "EPSG:4326", [x], [y])
    info = naip.read_chip(str(source), lon[0], lat[0], 6.0, tmp_path / "out.tif")
    with rasterio.open(tmp_path / "out.tif") as out:
        assert out.crs == crs and out.count == 4 and out.width == 20
        assert out.tags()["CONTENT"] == "USDA NAIP context imagery"
    assert info["res"] == pytest.approx(0.6)
