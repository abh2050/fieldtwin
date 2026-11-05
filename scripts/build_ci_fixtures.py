"""Build the committed CI workspace. Deterministic and offline.

OCD rows here are HAND-WRITTEN TEST DATA in OCD's real shape, because OCD states no license for
redistribution. API numbers use the unassigned-looking 9xxxx range and well names start with FIXTURE.
3W rows are real CC BY 4.0 records truncated by cut_fixtures.py.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pyarrow.parquet as pq

from pipelines.acquire.common.core import (
    FileEntry,
    aggregate_checksum,
    sha256_file,
    write_string_parquet,
)
from pipelines.acquire.nm_ocd.adapter import PRODUCTION_COLUMNS, WELL_COLUMNS, WELLHISTORY_COLUMNS
from pipelines.acquire.petrobras_3w.adapter import parse_instance

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "data" / "fixtures" / "ci_workspace"
NOTE = "FIXTURE: hand-written OCD-shaped rows for CI, not real records."
OCD_BATCH = "nm_ocd-fixture-20261105"
W3_BATCH = "petrobras_3w-fixture-2.0.0"
EPOCH = "2026-11-05T00:00:00Z"


def well(
    number: int, lat: float, lon: float, projection: str = "NAD83", status: str = "Active"
) -> dict:
    row = {column: None for column in WELL_COLUMNS}
    row.update(
        OBJECTID=number,
        id=f"30-015-9{number:04d}",
        name=f"FIXTURE WELL #{number:03d}",
        type="Gas",
        status=status,
        ogrid=999000 + number,
        ogrid_name="FIXTURE OPERATOR",
        county="Eddy",
        ulstr=f"A-{number:02d}-23S-28E",
        latitude=lat,
        longitude=lon,
        projection=projection,
        last_production_date=1785567600000,
        geometry_x=lon,
        geometry_y=lat,
    )
    return row


WELLS = [
    well(1, 32.2990, -104.0810),
    well(2, 32.3010, -104.0830),
    well(3, 32.2970, -104.0790),
    well(4, 32.3030, -104.0850),
    well(5, 33.3030, -104.0810),  # One degree north of its township peers.
    well(6, 32.2950, -104.0770, projection="NAD27"),  # Labels conflict across channels.
    well(7, 32.2930, -104.0750, projection=""),  # Label missing in one channel.
    well(8, 32.2910, -104.0730, status="Cancelled"),
]


def history(number: int, status: str, lat: float, lon: float) -> dict:
    row = {column: None for column in WELLHISTORY_COLUMNS}
    row.update(
        api=f"30-015-9{number:04d}",
        api_st_cde="30",
        api_cnty_cde="15",
        api_well_idn=f"9{number:04d}",
        eff_dte="2020-01-01T00:00:00",
        rec_termn_dte="9999-12-31T00:00:00",
        ogrid_cde=str(999000 + number),
        well_name=f"FIXTURE WELL #{number:03d}",
        well_typ_cde="G",
        latitude=f"{lat:.15e}",
        longitude=f"{lon:.15e}",
        datum="NAD83",
        status=status,
    )
    return row


HISTORY = [
    history(
        w["OBJECTID"], "C" if w["status"] == "Cancelled" else "A", w["latitude"], w["longitude"]
    )
    for w in WELLS
]
CLOSED = history(1, "N", 32.2990, -104.0810)
CLOSED.update(eff_dte="2018-01-01T00:00:00", rec_termn_dte="2020-01-01T00:00:00")
HISTORY.append(CLOSED)


def production(
    number: int, pool: str, kind: str, amount: str | None, month: int = 6, amended: str = "N"
) -> dict:
    return {
        "api": f"30-015-9{number:04d}",
        "api_st_cde": "30",
        "api_cnty_cde": "15",
        "api_well_idn": f"9{number:04d}",
        "pool_idn": pool,
        "prodn_mth": str(month),
        "prodn_yr": "2026",
        "ogrid_cde": str(999000 + number),
        "prd_knd_cde": f"{kind} ",
        "eff_dte": f"2026-{month + 2:02d}-10T19:00:31.220",
        "amend_ind": amended,
        "c115_wc_stat_cde": "F",
        "prod_amt": amount,
        "prodn_day_num": "30",
        "mod_dte": f"2026-{month + 2:02d}-10T19:02:28.627",
    }


PRODUCTION = [
    production(1, "97442", "G", "1000"),
    production(1, "97442", "O", "100"),
    production(1, "97442", "W", "500"),
    production(1, "98220", "G", "250"),  # A second completion of the same well.
    production(2, "97442", "G", "0", amended="Y"),
    production(5, "97442", "G", "750"),  # Production stays valid for the quarantined coordinate.
    production(6, "97442", "G", None, month=5),  # A null volume stays null.
]
QUARANTINE = [
    {
        "dataset": "wellhistory",
        "reason": "INVALID_COORDINATES",
        "record": {
            **history(4, "A", 0.0, 0.0),
            "eff_dte": "2017-01-01T00:00:00",
            "rec_termn_dte": "2018-01-01T00:00:00",
        },
    }
]


def xml_zip(tag: str, rows: list[dict], columns: list[str]) -> bytes:
    parts = ['<root xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">']
    parts.append(f'<xsd:schema xmlns:xsd="x"><xsd:element name="{tag}"/></xsd:schema>')
    for row in rows:
        cells = "".join(
            f'<{c} xsi:nil="true"/>' if row.get(c) is None else f"<{c}>{row[c]}</{c}>"
            for c in columns
        )
        parts.append(f'<{tag} xmlns="urn:x">{cells}</{tag}>')
    parts.append("</root>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(f"{tag}.xml", date_time=(2026, 11, 5, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, "".join(parts).encode("utf-16"))
    return buffer.getvalue()


def entry(path: Path, url: str, upstream: str | None = None) -> FileEntry:
    return FileEntry(
        path=path.relative_to(ROOT).as_posix(),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        source_url=url,
        upstream_checksum=upstream,
    )


def write_manifest(
    source, batch, version, files, total, accepted, rejected, datasets, notes
) -> None:
    path = ROOT / "data" / "manifests" / source / f"{batch}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "batch_id": batch,
        "source_system_id": source,
        "source_version": version,
        "config_sha256": hashlib.sha256(batch.encode()).hexdigest(),
        "ingestion_timestamp": EPOCH,
        "original_checksum": aggregate_checksum(files),
        "source_record_count": total,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "processing_status": "COMPLETE",
        "manifest_uri": f"data/manifests/{source}/{batch}.json",
        "license": {"explicit_license": "fixture"},
        "files": [vars(f) for f in files],
        "datasets": datasets,
        "notes": notes,
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def build_ocd() -> None:
    raw = ROOT / "data" / "raw" / "nm_ocd" / "20261105" / OCD_BATCH / "ftp"
    bronze = ROOT / "data" / "bronze" / "nm_ocd" / OCD_BATCH
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "wcproduction.zip").write_bytes(xml_zip("wcproduction", PRODUCTION, PRODUCTION_COLUMNS))
    (raw / "wellhistory.zip").write_bytes(xml_zip("wellhistory", HISTORY, WELLHISTORY_COLUMNS))
    stamp = {"provenance_class": "OBSERVED", "source_batch_id": OCD_BATCH}
    extra = list(stamp)
    write_string_parquet(
        bronze / "wells.parquet", [{**w, **stamp} for w in WELLS], WELL_COLUMNS + extra
    )
    write_string_parquet(
        bronze / "wellhistory.parquet",
        [{**h, **stamp} for h in HISTORY],
        ["api", *WELLHISTORY_COLUMNS, *extra],
    )
    write_string_parquet(
        bronze / "wcproduction.parquet",
        [{**p, **stamp} for p in PRODUCTION],
        ["api", *PRODUCTION_COLUMNS, *extra],
    )
    (bronze / "quarantine.jsonl").write_text("".join(json.dumps(q) + "\n" for q in QUARANTINE))
    files = [
        entry(raw / name, f"fixture://nm_ocd/{name}")
        for name in ("wcproduction.zip", "wellhistory.zip")
    ]
    accepted = len(WELLS) + len(HISTORY) + len(PRODUCTION)
    write_manifest(
        "nm_ocd",
        OCD_BATCH,
        "20261105",
        files,
        accepted + len(QUARANTINE),
        accepted,
        len(QUARANTINE),
        {"fixture": True},
        [NOTE],
    )


def build_3w() -> None:
    source = REPO / "data" / "fixtures" / "petrobras_3w"
    raw = ROOT / "data" / "raw" / "petrobras_3w" / "2.0.0" / W3_BATCH
    files, rows = [], []
    for parquet in sorted(source.glob("*.parquet")):
        label, name = parquet.name.split("_", 1)
        instance = parse_instance({"path": f"dataset/{label}/{name}", "sha": "fixture", "size": 0})
        dest = raw / instance.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pq.read_table(parquet), dest, compression="zstd")
        files.append(
            entry(dest, f"fixture://petrobras_3w/{instance.path}", "fixture:truncated-real-record")
        )
        rows.append(
            {
                "source_instance_id": instance.source_instance_id,
                "source_path": instance.path,
                "source_event_label": instance.label,
                "source_event_class": {2: "SPURIOUS_CLOSURE_OF_DHSV", 7: "SCALING_IN_PCK"}[
                    instance.label
                ],
                "real_or_simulated_source": instance.origin,
                "source_well_id": instance.source_well_id,
                "row_count": pq.ParquetFile(dest).metadata.num_rows,
                "git_blob_sha": "fixture",
                "provenance_class": instance.provenance_class,
                "source_batch_id": W3_BATCH,
            }
        )
    write_string_parquet(
        ROOT / "data" / "bronze" / "petrobras_3w" / W3_BATCH / "instances.parquet",
        rows,
        list(rows[0]),
    )
    write_manifest(
        "petrobras_3w",
        W3_BATCH,
        "2.0.0",
        files,
        len(rows),
        len(rows),
        0,
        {"commit": "fixture"},
        ["FIXTURE: real 3W records truncated to 300 rows. CC BY 4.0, Petrobras."],
    )


if __name__ == "__main__":
    build_ocd()
    build_3w()
    print(f"built {ROOT.relative_to(REPO)}")
