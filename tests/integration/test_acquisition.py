"""Adapters run end to end against fake transports, covering success and every failure path."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from pipelines.acquire import cli
from pipelines.acquire.common import core
from pipelines.acquire.common.core import git_blob_sha1
from pipelines.acquire.common.errors import (
    ChecksumMismatch,
    CountMismatch,
    InsufficientDisk,
    SchemaDrift,
    SelectionOutOfBounds,
    SourceUnavailable,
)
from pipelines.acquire.nm_ocd import adapter as ocd
from pipelines.acquire.petrobras_3w import adapter as w3
from tests.conftest import history_row, production_row, well_feature, xml_export, zipped

PLENTY = lambda _: SimpleNamespace(free=10**13)  # noqa: E731


class FakeHttp:
    def __init__(self, features, reported=None, outage=False):
        self.features, self.reported, self.outage = features, reported, outage
        self.calls = 0

    def get_json(self, url, params=None):
        self.calls += 1
        if self.outage:
            raise SourceUnavailable("ArcGIS down")
        if params.get("returnCountOnly"):
            return {"count": len(self.features) if self.reported is None else self.reported}
        return {"features": self.features, "exceededTransferLimit": False}

    def get_bytes(self, url, params=None):
        return b"{}"


class FakeFtp:
    def __init__(self, files, outage=False):
        self.files, self.outage = files, outage
        self.downloads = 0

    def stat(self, path):
        if self.outage:
            raise SourceUnavailable("FTP down")
        return len(self.files[Path(path).name]), "20261105012200"

    def download(self, path, dest, size, modified):
        self.downloads += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[Path(path).name])


def ocd_files(production=None, history=None):
    production = [production_row()] if production is None else production
    history = [history_row()] if history is None else history
    return {
        "OCD Interface v1.1 Data Dictionary.xlsx": b"dictionary",
        "wellhistory.zip": zipped("wellhistory.xml", xml_export("wellhistory", history)),
        "wcproduction.zip": zipped("wcproduction.xml", xml_export("wcproduction", production)),
    }


def assert_nothing_published(root: Path, source: str):
    assert core.load_manifests(root, source) == []
    assert not list((root / "data" / "bronze").rglob("*.parquet"))


def test_ocd_batch_preserves_grain_identity_and_provenance(workspace):
    other_well = production_row(api_well_idn="99999")
    old = production_row(prodn_yr="2010")
    oil = production_row(prd_knd_cde="O ", prod_amt="5")
    files = ocd_files(production=[production_row(), oil, other_well, old])
    manifest = ocd.run(
        workspace, http=FakeHttp([well_feature()]), ftp=FakeFtp(files), disk_usage=PLENTY
    )

    assert manifest["processing_status"] == core.COMPLETE
    batch = manifest["batch_id"]
    rows = pd.read_parquet(workspace / "data/bronze/nm_ocd" / batch / "wcproduction.parquet")
    assert len(rows) == 2  # Out-of-scope well and out-of-window year are excluded, not rejected.
    assert set(rows["prd_knd_cde"]) == {"G ", "O "}  # Original text retained.
    assert set(rows["provenance_class"]) == {"OBSERVED"}
    assert manifest["datasets"]["wcproduction"]["rows_scanned"] == 4
    assert manifest["datasets"]["wcproduction"]["reporting_grain"].startswith("well_completion")


def test_ocd_invalid_rows_are_quarantined_not_dropped(workspace):
    files = ocd_files(production=[production_row(), production_row(prod_amt="-1", eff_dte="x")])
    manifest = ocd.run(
        workspace, http=FakeHttp([well_feature()]), ftp=FakeFtp(files), disk_usage=PLENTY
    )
    assert manifest["rejected_count"] == 1
    assert manifest["datasets"]["quarantine_reasons"] == {"wcproduction:NEGATIVE_VOLUME": 1}
    lines = (
        workspace / "data/bronze/nm_ocd" / manifest["batch_id"] / "quarantine.jsonl"
    ).read_text()
    assert "NEGATIVE_VOLUME" in lines


def test_ocd_duplicate_production_key_is_quarantined(workspace):
    files = ocd_files(production=[production_row(), production_row()])
    manifest = ocd.run(
        workspace, http=FakeHttp([well_feature()]), ftp=FakeFtp(files), disk_usage=PLENTY
    )
    assert manifest["datasets"]["quarantine_reasons"] == {"wcproduction:DUPLICATE_CANDIDATE_KEY": 1}


def test_ocd_rerun_reuses_batch_without_network_or_download(workspace):
    ftp = FakeFtp(ocd_files())
    first = ocd.run(workspace, http=FakeHttp([well_feature()]), ftp=ftp, disk_usage=PLENTY)
    assert first["reused"] is False

    untouched_http, untouched_ftp = FakeHttp([well_feature()]), FakeFtp(ocd_files())
    second = ocd.run(workspace, http=untouched_http, ftp=untouched_ftp, disk_usage=PLENTY)
    assert second["reused"] is True
    assert second["original_checksum"] == first["original_checksum"]
    assert untouched_http.calls == 0 and untouched_ftp.downloads == 0


def test_ocd_refresh_of_an_unchanged_upstream_version_leaves_raw_immutable(workspace):
    first = ocd.run(
        workspace, http=FakeHttp([well_feature()]), ftp=FakeFtp(ocd_files()), disk_usage=PLENTY
    )
    ftp = FakeFtp(ocd_files())
    second = ocd.run(
        workspace, refresh=True, http=FakeHttp([well_feature()]), ftp=ftp, disk_usage=PLENTY
    )
    assert second["reused"] is True and ftp.downloads == 0
    assert second["batch_id"] == first["batch_id"]


def test_raw_files_are_read_only_and_checksums_match(workspace):
    manifest = ocd.run(
        workspace, http=FakeHttp([well_feature()]), ftp=FakeFtp(ocd_files()), disk_usage=PLENTY
    )
    for entry in manifest["files"]:
        path = workspace / entry["path"]
        assert core.sha256_file(path) == entry["sha256"]
        with pytest.raises(PermissionError):
            path.open("a")


@pytest.mark.parametrize(
    ("http", "ftp", "error"),
    [
        (FakeHttp([well_feature()], outage=True), FakeFtp(ocd_files()), SourceUnavailable),
        (FakeHttp([well_feature()]), FakeFtp(ocd_files(), outage=True), SourceUnavailable),
        (FakeHttp([well_feature()], reported=2), FakeFtp(ocd_files()), CountMismatch),
        (FakeHttp([well_feature()], reported=5000), FakeFtp(ocd_files()), SelectionOutOfBounds),
    ],
)
def test_ocd_failures_publish_nothing(workspace, http, ftp, error):
    with pytest.raises(error):
        ocd.run(workspace, http=http, ftp=ftp, disk_usage=PLENTY)
    assert_nothing_published(workspace, "nm_ocd")


def test_ocd_low_disk_stops_before_any_download(workspace):
    ftp = FakeFtp(ocd_files())
    with pytest.raises(InsufficientDisk):
        ocd.run(
            workspace,
            http=FakeHttp([well_feature()]),
            ftp=ftp,
            disk_usage=lambda _: SimpleNamespace(free=1),
        )
    assert ftp.downloads == 0
    assert_nothing_published(workspace, "nm_ocd")


def test_ocd_schema_drift_stops_the_batch(workspace):
    drifted = production_row()
    del drifted["prod_amt"]
    with pytest.raises(SchemaDrift, match="prod_amt"):
        ocd.run(
            workspace,
            http=FakeHttp([well_feature()]),
            ftp=FakeFtp(ocd_files(production=[drifted])),
            disk_usage=PLENTY,
        )
    assert core.load_manifests(workspace, "nm_ocd") == []


def fake_3w_repo(tmp_path, tamper=False):
    """A small repo with real Parquet layout, served by a fake HTTP client."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"timestamp": [1], "class": [2], "state": [0]})
    pq.write_table(table, tmp_path / "x.parquet")
    parquet = (tmp_path / "x.parquet").read_bytes()
    ini = (
        b"[VERSION]\nDATASET = 2.0.0\n[EVENTS]\nNAMES = NORMAL, EV\n"
        b"[NORMAL]\nLABEL = 0\n[EV]\nLABEL = 2\n"
    )
    contents = {
        "dataset/dataset.ini": ini,
        "3W_DATASET_STRUCTURE.md": b"s",
        "LICENSE.md": b"l",
        "README.md": b"r",
        "CITATION.md": b"c",
        "dataset/2/WELL-00001_20170201010207.parquet": parquet,
        "dataset/2/SIMULATED_00001.parquet": parquet,
    }
    tree = {
        "truncated": False,
        "tree": [
            {"path": p, "sha": git_blob_sha1(b), "size": len(b), "type": "blob"}
            for p, b in contents.items()
        ],
    }

    class Client:
        downloads = 0

        def get_bytes(self, url, params=None):
            if "git/trees" in url:
                return json.dumps(tree).encode()
            Client.downloads += 1
            body = contents[url.split("/", 6)[6]]
            return body + b"tampered" if tamper and url.endswith(".parquet") else body

    return Client()


def test_3w_batch_keeps_origin_and_source_identity(workspace, tmp_path):
    manifest = w3.run(workspace, http=fake_3w_repo(tmp_path), disk_usage=PLENTY)
    assert manifest["processing_status"] == core.COMPLETE
    index = pd.read_parquet(
        workspace / "data/bronze/petrobras_3w" / manifest["batch_id"] / "instances.parquet"
    ).set_index("source_instance_id")
    real = index.loc["WELL-00001_20170201010207"]
    assert (real["real_or_simulated_source"], real["source_well_id"]) == ("REAL", "WELL-00001")
    assert real["provenance_class"] == "OBSERVED"
    simulated = index.loc["SIMULATED_00001"]
    assert simulated["real_or_simulated_source"] == "SIMULATED"
    assert simulated["provenance_class"] == "SYNTHETIC"
    assert pd.isna(simulated["source_well_id"])


def test_3w_tampered_file_fails_and_publishes_nothing(workspace, tmp_path):
    with pytest.raises(ChecksumMismatch):
        w3.run(workspace, http=fake_3w_repo(tmp_path, tamper=True), disk_usage=PLENTY)
    assert_nothing_published(workspace, "petrobras_3w")


def test_3w_rerun_downloads_nothing(workspace, tmp_path):
    first = w3.run(workspace, http=fake_3w_repo(tmp_path), disk_usage=PLENTY)
    client = fake_3w_repo(tmp_path)
    type(client).downloads = 0
    second = w3.run(workspace, http=client, disk_usage=PLENTY)
    assert second["reused"] is True and client.downloads == 0
    assert second["original_checksum"] == first["original_checksum"]


def test_3w_low_disk_stops_before_any_download(workspace, tmp_path):
    client = fake_3w_repo(tmp_path)
    type(client).downloads = 0
    with pytest.raises(InsufficientDisk):
        w3.run(workspace, http=client, disk_usage=lambda _: SimpleNamespace(free=1))
    assert client.downloads == 0


@pytest.mark.parametrize("source", ["nm_ocd", "petrobras_3w"])
def test_failed_acquisition_reports_failure_and_substitutes_nothing(
    workspace, monkeypatch, capsys, source
):
    """A failed source yields exit 1 and a report, never generated or alternate data."""

    def outage(**kwargs):
        raise SourceUnavailable("endpoint down")

    monkeypatch.setitem(cli.ADAPTERS, source, outage)
    monkeypatch.setattr(core, "REPO_ROOT", workspace)
    monkeypatch.setattr(cli.core, "REPO_ROOT", workspace)
    assert cli.main([source]) == 1
    report = json.loads((workspace / f"reports/ingestion/{source}_failure_latest.json").read_text())
    assert report["processing_status"] == "FAILED"
    assert report["substitute_data_produced"] is False
    assert "endpoint down" in report["error"]
    assert_nothing_published(workspace, source)


def test_adapters_contain_no_fallback_source():
    """GO-TECH and similar mirrors must never be used as a silent replacement."""
    from tests.conftest import REPO_ROOT

    for path in (REPO_ROOT / "pipelines" / "acquire").rglob("*.py"):
        body = path.read_text().lower()
        assert "octane.nmt.edu" not in body and "nhnm-gisweb" not in body, path
