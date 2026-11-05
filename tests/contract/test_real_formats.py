"""Contract tests against fixtures cut from real downloads."""

import configparser
import json

import pyarrow.parquet as pq
import pytest
import yaml

from pipelines.acquire.common.core import Quarantine
from pipelines.acquire.nm_ocd.adapter import (
    PRODUCTION_COLUMNS,
    WELL_COLUMNS,
    WELLHISTORY_COLUMNS,
)
from pipelines.acquire.nm_ocd.validate import api_from_parts, validate_wells
from pipelines.acquire.nm_ocd.xmlstream import iter_rows
from pipelines.acquire.petrobras_3w.adapter import parse_instance, read_dataset_version
from pipelines.profile.petrobras_3w import profile_instance
from tests.conftest import REPO_ROOT

FIXTURES = REPO_ROOT / "data" / "fixtures"
LOCAL = REPO_ROOT / "data" / "fixtures_local"
CI_OCD = FIXTURES / "ci_workspace/data/raw/nm_ocd/20261105/nm_ocd-fixture-20261105/ftp"
CONTRACTS = REPO_ROOT / "data_contracts" / "sources"
NM = {"lat_min": 31.3, "lat_max": 37.1, "lon_min": -109.1, "lon_max": -103.0}


@pytest.mark.acquired
def test_real_production_rows_match_the_contract():
    rows = list(iter_rows(LOCAL / "nm_ocd/wcproduction.zip", "wcproduction.xml", "wcproduction"))
    assert len(rows) == 25
    contract = yaml.safe_load((CONTRACTS / "nm_ocd.yaml").read_text())
    required = contract["datasets"]["wcproduction"]["required_columns"]
    assert set(required) <= set(rows[0])
    assert set(PRODUCTION_COLUMNS) == set(rows[0])
    assert all(api_from_parts(row) for row in rows)


@pytest.mark.acquired
def test_real_history_rows_match_the_adapter_columns():
    rows = list(iter_rows(LOCAL / "nm_ocd/wellhistory.zip", "wellhistory.xml", "wellhistory"))
    assert len(rows) == 25
    assert set(WELLHISTORY_COLUMNS) == set(rows[0])


@pytest.mark.acquired
def test_real_arcgis_features_validate_and_match_the_adapter(tmp_path):
    page = json.loads((LOCAL / "nm_ocd/arcgis_page.json").read_text())
    accepted = validate_wells(page["features"], NM, Quarantine(tmp_path / "q.jsonl"))
    assert accepted
    assert set(accepted[0]) == set(WELL_COLUMNS)


@pytest.mark.parametrize(
    ("glob", "origin", "label"),
    [("2_WELL-*", "REAL", 2), ("2_SIMULATED_*", "SIMULATED", 2), ("7_DRAWN_*", "HAND_DRAWN", 7)],
)
def test_real_3w_files_match_dataset_ini(glob, origin, label):
    path = sorted((FIXTURES / "petrobras_3w").glob(glob))[0]
    name = path.name.split("_", 1)[1]
    instance = parse_instance({"path": f"dataset/{label}/{name}", "sha": "a", "size": 1})
    assert instance.origin == origin

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(FIXTURES / "petrobras_3w/dataset.ini")
    assert set(pq.read_schema(path).names) == set(parser["PARQUET_FILE_PROPERTIES"])

    profile = profile_instance(path, label)
    assert profile["non_increasing_steps"] == 0
    assert profile["unexpected_labels"] == []


def test_pinned_ini_has_the_contract_version():
    contract = yaml.safe_load((CONTRACTS / "petrobras_3w.yaml").read_text())
    assert (
        read_dataset_version(FIXTURES / "petrobras_3w/dataset.ini") == contract["dataset_version"]
    )


def test_every_fixture_records_where_it_came_from():
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    for relative in provenance["sources"]:
        assert (FIXTURES / relative).exists()


def test_fixture_production_zip_parses_with_the_real_parser():
    rows = list(iter_rows(CI_OCD / "wcproduction.zip", "wcproduction.xml", "wcproduction"))
    assert set(PRODUCTION_COLUMNS) == set(rows[0])
    assert any(row["prod_amt"] is None for row in rows)


def test_committed_ocd_fixtures_are_hand_written_not_source_records():
    manifest = json.loads(
        (FIXTURES / "ci_workspace/data/manifests/nm_ocd/nm_ocd-fixture-20261105.json").read_text()
    )
    assert "hand-written" in manifest["notes"][0]
    assert not (FIXTURES / "nm_ocd").exists()
    assert "data/fixtures_local/" in (REPO_ROOT / ".gitignore").read_text()
