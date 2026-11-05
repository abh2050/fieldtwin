"""Checks against real public endpoints. Run with `pytest -m live -o addopts=''`."""

import pytest

from pipelines.acquire.common.core import REPO_ROOT, load_yaml
from pipelines.acquire.common.transport import Ftp, Http
from pipelines.acquire.nm_ocd.adapter import WELL_COLUMNS
from pipelines.acquire.petrobras_3w.adapter import TREE_URL

pytestmark = pytest.mark.live
OCD = load_yaml(REPO_ROOT / "config/sources/nm_ocd.yaml")
W3 = load_yaml(REPO_ROOT / "config/sources/petrobras_3w.yaml")


def test_arcgis_selection_is_in_range_and_has_contract_fields():
    url = OCD["arcgis"]["layer_url"]
    http = Http()
    count = http.get_json(
        f"{url}/query", {"where": OCD["arcgis"]["where"], "returnCountOnly": "true", "f": "json"}
    )["count"]
    assert OCD["arcgis"]["min_records"] <= count <= OCD["arcgis"]["max_records"]
    fields = {f["name"] for f in http.get_json(url, {"f": "json"})["fields"]}
    assert set(WELL_COLUMNS) - {"geometry_x", "geometry_y"} <= fields


@pytest.mark.parametrize("name", list(OCD["ftp"]["files"]))
def test_ftp_files_exist(name):
    path = f"{OCD['ftp']['base_path']}/{OCD['ftp']['files'][name]}"
    size, modified = Ftp(OCD["ftp"]["host"]).stat(path)
    assert size > 0 and len(modified) >= 14


def test_pinned_3w_commit_is_still_available():
    url = TREE_URL.format(repo=W3["repo"], commit=W3["commit"])
    tree = Http().get_json(url)
    assert not tree["truncated"]
    paths = {entry["path"] for entry in tree["tree"]}
    assert set(W3["metadata_files"]) <= paths
