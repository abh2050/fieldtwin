"""Gate 6 checks that need the acquired aerial batches. Run with `pytest -m acquired -o addopts=''`."""

from __future__ import annotations

import json

import pandas as pd
import pytest
import rasterio
from rasterio.warp import transform

from packages.inspection.geodesy import haversine_m
from pipelines.acquire.common.core import REPO_ROOT, sha256_file
from pipelines.inspection import associate, evidence
from pipelines.inspection.wells import latest_batch

pytestmark = pytest.mark.acquired


def test_association_reruns_to_the_same_summary():
    before = json.loads((REPO_ROOT / associate.SILVER / "summary.json").read_text())
    assert associate.run(REPO_ROOT) == json.loads(json.dumps(before))


def test_every_chip_is_centred_on_its_well_and_unchanged():
    batch = latest_batch(REPO_ROOT, "naip")["batch_id"]
    chips = pd.read_parquet(REPO_ROOT / "data/bronze/naip" / batch / "chips.parquet")
    wells = pd.read_parquet(REPO_ROOT / associate.SILVER / "registry_wells.parquet").set_index(
        "source_asset_id"
    )
    for chip in chips.to_dict("records"):
        path = REPO_ROOT / chip["path"]
        assert sha256_file(path) == chip["sha256"]
        with rasterio.open(path) as src:
            x, y = src.xy(src.height // 2, src.width // 2)
            lon, lat = transform(src.crs, "EPSG:4326", [x], [y])
        well = wells.loc[chip["source_asset_id"]]
        assert haversine_m(lat[0], lon[0], well["latitude"], well["longitude"]) < 1.5


def test_every_rendered_evidence_line_passes_the_claim_guard():
    result = evidence.run(REPO_ROOT)
    assert result["cards"] == 60 and result["rendered_lines_checked"] > 500


def test_no_plume_is_linked_to_a_well_outside_the_usable_set():
    links = pd.read_parquet(REPO_ROOT / associate.SILVER / "proximity_links.parquet")
    wells = pd.read_parquet(REPO_ROOT / associate.SILVER / "registry_wells.parquet")
    usable = set(wells[wells.spatial_status == "USABLE"].source_asset_id)
    assert set(links.source_asset_id) <= usable
    assert (links.verification_status == "UNVERIFIED").all() and links.confidence.isna().all()
