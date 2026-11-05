"""Shared fixtures. The default suite is offline: any network attempt fails the test."""

from __future__ import annotations

import io
import os
import shutil
import socket
import uuid
import zipfile
from pathlib import Path

import psycopg
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    # Database tests talk to the local PostGIS service, not to external endpoints.
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("db"):
        return

    def refuse(*args, **kwargs):
        raise AssertionError("Offline test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """An isolated repo root holding copies of the real source configs."""
    (tmp_path / "config").mkdir()
    shutil.copytree(REPO_ROOT / "config" / "sources", tmp_path / "config" / "sources")
    path = tmp_path / "config" / "sources" / "nm_ocd.yaml"
    config = yaml.safe_load(path.read_text())
    config["arcgis"]["min_records"] = 1  # Test data is smaller than the real target range.
    path.write_text(yaml.safe_dump(config))
    return tmp_path


CI_WORKSPACE = REPO_ROOT / "data" / "fixtures" / "ci_workspace"


def _admin_url() -> str:
    from packages.repositories.database import database_url

    return database_url()


def _database_url(name: str) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    return make_conninfo(**{**conninfo_to_dict(_admin_url()), "dbname": name})


@pytest.fixture
def fresh_database():
    """An empty database, removed afterwards. Yields its URL."""
    name = f"ft_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_admin_url(), autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    try:
        yield _database_url(name)
    finally:
        with psycopg.connect(_admin_url(), autocommit=True) as admin:
            admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture(scope="session")
def canonical_database():
    """Migrated, seeded, and loaded from the committed CI fixtures. Yields its URL."""
    from packages.repositories.database import migrate
    from pipelines.normalize.load import load_all
    from pipelines.normalize.seed import seed

    name = f"ft_session_{uuid.uuid4().hex[:12]}_{os.getpid()}"
    with psycopg.connect(_admin_url(), autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    url = _database_url(name)
    try:
        with psycopg.connect(url) as conn:
            migrate(conn)
            seed(conn)
            load_all(conn, CI_WORKSPACE)
        yield url
    finally:
        with psycopg.connect(_admin_url(), autocommit=True) as admin:
            admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture
def db(canonical_database):
    """A connection whose changes are always rolled back."""
    with psycopg.connect(canonical_database) as conn:
        with conn.transaction(force_rollback=True):
            yield conn


def xml_export(row_tag: str, rows: list[dict[str, str | None]], close_root: bool = True) -> bytes:
    """Hand-written test rows in OCD's export shape: UTF-16 with a BOM and xsi:nil for nulls."""
    parts = ['<root xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">']
    parts.append(f'<xsd:schema xmlns:xsd="x"><xsd:element name="{row_tag}"/></xsd:schema>')
    for row in rows:
        cells = "".join(
            f'<{k} xsi:nil="true"/>' if v is None else f"<{k}>{v}</{k}>" for k, v in row.items()
        )
        parts.append(f'<{row_tag} xmlns="urn:x">{cells}</{row_tag}>')
    if close_root:
        parts.append("</root>")
    return "".join(parts).encode("utf-16")


def zipped(member: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, data)
    return buffer.getvalue()


def production_row(**overrides) -> dict[str, str | None]:
    row = {
        "api_st_cde": "30",
        "api_cnty_cde": "15",
        "api_well_idn": "90001",
        "pool_idn": "97442",
        "prodn_mth": "6",
        "prodn_yr": "2026",
        "ogrid_cde": "111",
        "prd_knd_cde": "G ",
        "eff_dte": "2026-06-30T00:00:00",
        "amend_ind": "N",
        "c115_wc_stat_cde": "F",
        "prod_amt": "1000",
        "prodn_day_num": "30",
        "mod_dte": "2026-08-01T00:00:00",
    }
    return {**row, **overrides}


def history_row(**overrides) -> dict[str, str | None]:
    from pipelines.acquire.nm_ocd.adapter import WELLHISTORY_COLUMNS

    row = {column: "x" for column in WELLHISTORY_COLUMNS}
    row.update(
        api_st_cde="30",
        api_cnty_cde="15",
        api_well_idn="90001",
        eff_dte="2020-01-01T00:00:00",
        rec_termn_dte="9999-12-31T00:00:00",
        latitude="3.2200000e+001",
        longitude="-1.041000e+002",
    )
    return {**row, **overrides}


def well_feature(api: str = "30-015-90001", **overrides) -> dict:
    attributes = {
        "OBJECTID": 1,
        "id": api,
        "type": "Gas",
        "status": "Active",
        "county": "Eddy",
        "ulstr": "D-18-24S-28E",
        "latitude": 32.22,
        "longitude": -104.1,
        "projection": "NAD83",
        **overrides,
    }
    return {"attributes": attributes, "geometry": {"x": -104.1, "y": 32.22}}
