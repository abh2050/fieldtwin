"""Hashing, disk preflight, immutability, and network failure behavior."""

import ftplib
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from tenacity import stop_after_attempt, wait_none

from pipelines.acquire.common import core
from pipelines.acquire.common.errors import InsufficientDisk, MalformedSource, SourceUnavailable
from pipelines.acquire.common.transport import Ftp, Http


def test_git_blob_hash_matches_known_git_value():
    # `printf 'hello\n' | git hash-object --stdin`
    assert core.git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_preflight_refuses_when_floor_would_be_crossed(tmp_path):
    usage = lambda _: SimpleNamespace(free=6_000)  # noqa: E731
    with pytest.raises(InsufficientDisk):
        core.preflight_disk(tmp_path, needed_bytes=2_000, floor_bytes=5_000, disk_usage=usage)
    assert core.preflight_disk(tmp_path, 500, 5_000, disk_usage=usage) == 6_000


def test_freeze_makes_files_read_only(tmp_path):
    target = tmp_path / "a" / "file.bin"
    target.parent.mkdir()
    target.write_bytes(b"x")
    core.freeze_tree(tmp_path)
    assert not os.access(target, os.W_OK)


def test_quarantine_keeps_every_record_with_a_reason(tmp_path):
    quarantine = core.Quarantine(tmp_path / "q.jsonl")
    quarantine.add("wells", "INVALID_API", {"id": "bad"})
    quarantine.add("wells", "INVALID_API", {"id": "worse"})
    assert quarantine.count == 2
    assert quarantine.reasons == {"wells:INVALID_API": 2}
    assert '"worse"' in (tmp_path / "q.jsonl").read_text()


@pytest.fixture
def no_retry_wait(monkeypatch):
    for function in (Http._get, Ftp._stat, Ftp._retrieve):
        monkeypatch.setattr(function.retry, "wait", wait_none())
        monkeypatch.setattr(function.retry, "stop", stop_after_attempt(2))


def http_returning(handler) -> Http:
    client = Http()
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_http_outage_raises_instead_of_returning_empty(no_retry_wait):
    def down(request):
        raise httpx.ConnectError("unreachable")

    with pytest.raises(SourceUnavailable):
        http_returning(down).get_json("https://example.test/query")


def test_arcgis_error_inside_a_200_response_is_a_failure(no_retry_wait):
    client = http_returning(lambda r: httpx.Response(200, json={"error": {"code": 400}}))
    with pytest.raises(SourceUnavailable):
        client.get_json("https://example.test/query")


def test_non_json_response_is_malformed(no_retry_wait):
    client = http_returning(lambda r: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(MalformedSource):
        client.get_json("https://example.test/query")


class FakeFtp:
    """Stands in for ftplib.FTP and serves bytes from `payload`."""

    payload = b"0123456789"
    modified = "20261105010000"
    reported_size: int | None = None
    fail = False
    rest_values: list = []

    def __init__(self, host, timeout=None):
        if FakeFtp.fail:
            raise OSError("connection refused")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self):
        pass

    def voidcmd(self, command):
        return f"213 {FakeFtp.modified}"

    def size(self, path):
        return FakeFtp.reported_size if FakeFtp.reported_size is not None else len(FakeFtp.payload)

    def retrbinary(self, command, callback, blocksize, rest=None):
        FakeFtp.rest_values.append(rest)
        callback(FakeFtp.payload[rest or 0 :])


@pytest.fixture
def fake_ftp(monkeypatch, no_retry_wait):
    FakeFtp.payload, FakeFtp.modified, FakeFtp.reported_size = (
        b"0123456789",
        "20261105010000",
        None,
    )
    FakeFtp.fail, FakeFtp.rest_values = False, []
    monkeypatch.setattr(ftplib, "FTP", FakeFtp)
    return FakeFtp


def test_ftp_resumes_a_partial_file_when_upstream_is_unchanged(fake_ftp, tmp_path: Path):
    dest = tmp_path / "f.zip"
    (tmp_path / "f.zip.part").write_bytes(b"01234")
    (tmp_path / "f.zip.part.modified").write_text(fake_ftp.modified)
    Ftp("host").download("/f.zip", dest, 10, fake_ftp.modified)
    assert dest.read_bytes() == b"0123456789"
    assert fake_ftp.rest_values == [5]


def test_ftp_discards_a_partial_file_from_an_older_upstream_version(fake_ftp, tmp_path: Path):
    dest = tmp_path / "f.zip"
    (tmp_path / "f.zip.part").write_bytes(b"stale")
    (tmp_path / "f.zip.part.modified").write_text("20200101000000")
    Ftp("host").download("/f.zip", dest, 10, fake_ftp.modified)
    assert dest.read_bytes() == b"0123456789"
    assert fake_ftp.rest_values == [None]


def test_ftp_rejects_a_file_that_changes_during_download(fake_ftp, tmp_path: Path):
    dest = tmp_path / "f.zip"
    with pytest.raises(SourceUnavailable, match="changed upstream"):
        Ftp("host").download("/f.zip", dest, 10, "20200101000000")
    assert not dest.exists()


def test_ftp_rejects_a_short_download(fake_ftp, tmp_path: Path):
    dest = tmp_path / "f.zip"
    with pytest.raises(MalformedSource):
        Ftp("host").download("/f.zip", dest, 999, fake_ftp.modified)
    assert not dest.exists()


def test_ftp_outage_raises(fake_ftp):
    fake_ftp.fail = True
    with pytest.raises(SourceUnavailable):
        Ftp("host").stat("/f.zip")
