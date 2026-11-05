"""Load acquired batches into the canonical schema in one transaction per batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
import yaml

from packages.domain.models import Canonical
from packages.repositories.database import REPO_ROOT, connect
from pipelines.profile.common import latest_complete

from . import ocd, petrobras_3w
from .seed import contract


def _rows(models: list[Any]) -> list[dict[str, Any]]:
    return [m.model_dump(mode="json") for m in models]


def _jsonify(rows: list[dict[str, Any]], *columns: str) -> list[dict[str, Any]]:
    for row in rows:
        for column in columns:
            row[column] = json.dumps(row[column])
    return rows


def _insert_many(conn: psycopg.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(f'%({c})s' for c in columns)})"
    )
    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)


def _insert_batch(conn: psycopg.Connection, manifest: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO ingestion_batches (batch_id, source_system_id, source_version, ingestion_timestamp,
             original_checksum, source_record_count, accepted_count, rejected_count, processing_status,
             manifest_uri, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            manifest["batch_id"],
            manifest["source_system_id"],
            manifest["source_version"],
            manifest["ingestion_timestamp"],
            manifest["original_checksum"],
            manifest["source_record_count"],
            manifest["accepted_count"],
            manifest["rejected_count"],
            manifest["processing_status"],
            manifest["manifest_uri"],
            json.dumps(manifest["notes"]),
        ),
    )
    _insert_many(
        conn,
        "batch_files",
        [
            {
                "batch_id": manifest["batch_id"],
                "path": f["path"],
                "sha256": f["sha256"],
                "size_bytes": f["size_bytes"],
                "source_url": f["source_url"],
                "source_modified": f.get("source_modified"),
                "upstream_checksum": f.get("upstream_checksum"),
            }
            for f in manifest["files"]
        ],
    )


def _insert_assets(conn: psycopg.Connection, assets: list[Any]) -> None:
    """Build a geometry only for USABLE assets, from the reported values."""
    rows = _jsonify(_rows(assets), "attributes")
    if not rows:
        return
    columns = list(rows[0])
    for row in rows:
        usable = row["spatial_status"] == "USABLE"
        row["geometry_x"] = row["reported_longitude"] if usable else None
        row["geometry_y"] = row["reported_latitude"] if usable else None
    values = ", ".join(f"%({c})s" for c in columns)
    # ST_MakePoint returns NULL for NULL input, so non-usable assets get no geometry.
    sql = f"""INSERT INTO source_assets ({", ".join(columns)}, geometry) VALUES ({values},
              ST_SetSRID(ST_MakePoint(%(geometry_x)s::float8, %(geometry_y)s::float8), 4269))"""
    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)


def _insert_identifiers(conn: psycopg.Connection, wells: list[Any], source: str, kind: str) -> None:
    _insert_many(
        conn,
        "source_identifiers",
        [
            {
                "source_system_id": source,
                "canonical_asset_id": w.source_asset_id,
                "external_identifier": w.external_identifier,
                "identifier_type": kind,
                "verification_status": "VERIFIED",
            }
            for w in wells
        ],
    )


def _insert_exceptions(conn: psycopg.Connection, exceptions: list[Any]) -> None:
    _insert_many(
        conn, "data_quality_exceptions", _jsonify(_rows(exceptions), "original_values", "evidence")
    )


def _batch_loaded(conn: psycopg.Connection, batch_id: str) -> bool:
    return bool(
        conn.execute("SELECT 1 FROM ingestion_batches WHERE batch_id = %s", (batch_id,)).fetchone()
    )


def status_decode(conn: psycopg.Connection, root: Path) -> dict[str, str]:
    return yaml.safe_load((root / "data_contracts" / "sources" / "nm_ocd_codes.yaml").read_text())[
        "wellhistory_status"
    ]


def load_ocd(conn: psycopg.Connection, root: Path, repo: Path = REPO_ROOT) -> dict[str, Any]:
    manifest = latest_complete(root, ocd.SOURCE)
    batch_id = manifest["batch_id"]
    if _batch_loaded(conn, batch_id):
        return {"batch_id": batch_id, "already_loaded": True}

    bronze = root / "data" / "bronze" / ocd.SOURCE / batch_id
    config = yaml.safe_load((repo / "config" / "sources" / "nm_ocd.yaml").read_text())
    units = contract("ocd_production_units.yaml")
    rules = {
        r["product_kind"]: r["unit_id"]
        for r in units["rules"]
        if r["verification_status"] == "VERIFIED"
    }
    uri = next(f["path"] for f in manifest["files"] if f["path"].endswith("wcproduction.zip"))
    canonical = ocd.normalize_batch(
        pd.read_parquet(bronze / "wells.parquet"),
        pd.read_parquet(bronze / "wellhistory.parquet"),
        pd.read_parquet(bronze / "wcproduction.parquet"),
        bronze / "quarantine.jsonl",
        status_decode(conn, repo),
        rules,
        units["unit_system"],
        units["reporting_grain"],
        uri,
        config["bounds"]["eddy_county_approx"],
        batch_id,
    )
    with conn.transaction():
        _insert_batch(conn, manifest)
        _insert_assets(conn, canonical.wells)
        _insert_identifiers(conn, canonical.wells, ocd.SOURCE, "API_NUMBER")
        _insert_assets(conn, canonical.completions)
        _insert_many(conn, "source_asset_history", _jsonify(_rows(canonical.history), "attributes"))
        _insert_many(conn, "production_records", _rows(canonical.production))
        _insert_many(conn, "source_reconciliation_evidence", _rows(canonical.evidence))
        _insert_exceptions(conn, canonical.exceptions)
    return {
        "batch_id": batch_id,
        "wells": len(canonical.wells),
        "completions": len(canonical.completions),
        "history": len(canonical.history),
        "production": len(canonical.production),
        "reconciliation_evidence": len(canonical.evidence),
        "exceptions": len(canonical.exceptions),
    }


def load_3w(conn: psycopg.Connection, root: Path) -> dict[str, Any]:
    manifest = latest_complete(root, petrobras_3w.SOURCE)
    batch_id = manifest["batch_id"]
    if _batch_loaded(conn, batch_id):
        return {"batch_id": batch_id, "already_loaded": True}
    index = pd.read_parquet(
        root / "data" / "bronze" / petrobras_3w.SOURCE / batch_id / "instances.parquet"
    )
    variables = contract("3w_aether_compatibility.yaml")["variables"]
    canonical = petrobras_3w.normalize_batch(index, root, manifest, variables)
    with conn.transaction():
        _insert_batch(conn, manifest)
        _insert_assets(conn, canonical.wells)
        _insert_identifiers(conn, canonical.wells, petrobras_3w.SOURCE, "ANONYMIZED_WELL_ID")
        _insert_many(conn, "telemetry_events", _rows(canonical.events))
        _insert_many(conn, "observations", _rows(canonical.observations))
        _insert_exceptions(conn, canonical.exceptions)
    return {
        "batch_id": batch_id,
        "wells": len(canonical.wells),
        "events": len(canonical.events),
        "observations": len(canonical.observations),
        "exceptions": len(canonical.exceptions),
    }


def load_all(conn: psycopg.Connection, root: Path) -> dict[str, dict[str, Any]]:
    return {"nm_ocd": load_ocd(conn, root), "petrobras_3w": load_3w(conn, root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="workspace holding data/")
    args = parser.parse_args(argv)
    with connect() as conn:
        print(json.dumps(load_all(conn, args.root), indent=2))
    return 0


__all__ = ["Canonical", "load_3w", "load_all", "load_ocd"]

if __name__ == "__main__":
    raise SystemExit(main())
