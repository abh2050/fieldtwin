"""NM OCD acquisition: well registry from ArcGIS, production and well history from FTP.

Provenance: everything written here is OBSERVED. Nothing is linked to AETHER Field.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from pipelines.acquire.common import core
from pipelines.acquire.common.core import BatchManifest, FileEntry, Quarantine
from pipelines.acquire.common.errors import CountMismatch, SchemaDrift, SelectionOutOfBounds
from pipelines.acquire.common.transport import Ftp, Http

from .validate import (
    api_from_parts,
    production_key,
    production_rejection,
    validate_wells,
    wellhistory_rejection,
)
from .xmlstream import iter_rows

SOURCE = "nm_ocd"
_LOG = core.get_logger("acquire.nm_ocd")

WELL_COLUMNS = [
    "OBJECTID", "id", "name", "type", "status", "sub_type_code", "ogrid", "ogrid_name",
    "district_code", "district", "county_code", "county", "ulstr", "latitude", "longitude",
    "projection", "directional_status", "details", "files", "year_spudded", "spud_date",
    "lease_type", "measured_vertical_depth", "true_vertical_depth", "pool_id_list",
    "last_production_date", "plug_date", "GlobalID", "geometry_x", "geometry_y",
]  # fmt: skip
PRODUCTION_COLUMNS = [
    "api_st_cde", "api_cnty_cde", "api_well_idn", "pool_idn", "prodn_mth", "prodn_yr",
    "ogrid_cde", "prd_knd_cde", "eff_dte", "amend_ind", "c115_wc_stat_cde", "prod_amt",
    "prodn_day_num", "mod_dte",
]  # fmt: skip
WELLHISTORY_COLUMNS = [
    "api_st_cde", "api_cnty_cde", "api_well_idn", "eff_dte", "rec_termn_dte", "ogrid_cde",
    "well_name", "prod_prop_idn", "prop_fm_desc", "well_nbr_idn", "well_typ_cde", "lease_typ_cde",
    "ocd_district", "last_apd_status", "last_apd_apr_date", "last_apd_cancel_date", "latitude",
    "longitude", "datum", "sdiv_twp_idn", "sdiv_rng_idn", "sdiv_sect_num", "sdiv_unlt_idn",
    "ocd_unlt_idn", "lot_idn", "ftg_ns_num", "ftg_ew_num", "ns_cde", "ew_cde", "status",
    "spud_dte", "plug_dte", "directional_status", "completed_in_adjacent_state", "elev_gl_num",
    "dpth_tgt_num", "dpth_tvd_num", "dpth_mvd_num",
]  # fmt: skip


def load_config(root: Path) -> dict[str, Any]:
    return core.load_yaml(root / "config" / "sources" / "nm_ocd.yaml")


def first_month_in_window(modified: str, months: int) -> tuple[int, int]:
    """First (year, month) of a window of `months` months ending at a YYYYMMDD... timestamp."""
    index = int(modified[:4]) * 12 + int(modified[4:6]) - 1 - (months - 1)
    return index // 12, index % 12 + 1


def _in_window(row: dict[str, str | None], first: tuple[int, int]) -> bool:
    try:
        return (int(str(row["prodn_yr"])), int(str(row["prodn_mth"]))) >= first
    except (KeyError, TypeError, ValueError):
        return True  # Unreadable periods stay in scope so validation can quarantine them.


def _require_columns(row: dict[str, Any], expected: list[str], dataset: str) -> None:
    missing = [column for column in expected if column not in row]
    if missing:
        raise SchemaDrift(f"{dataset} is missing contract columns: {missing}")


def fetch_well_pages(http: Http, cfg: dict[str, Any], raw_dir: Path) -> list[dict[str, Any]]:
    """Save each raw ArcGIS page, then confirm the total against the service's own count."""
    arcgis = cfg["arcgis"]
    query_url = f"{arcgis['layer_url']}/query"
    expected = http.get_json(
        query_url, {"where": arcgis["where"], "returnCountOnly": "true", "f": "json"}
    )["count"]
    if not arcgis["min_records"] <= expected <= arcgis["max_records"]:
        raise SelectionOutOfBounds(
            f"Selection has {expected} wells, outside "
            f"{arcgis['min_records']}-{arcgis['max_records']}. Update the configured rule."
        )

    (raw_dir / "arcgis").mkdir(parents=True, exist_ok=True)
    (raw_dir / "arcgis" / "layer_metadata.json").write_bytes(
        http.get_bytes(arcgis["layer_url"], {"f": "pjson"})
    )
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = http.get_json(
            query_url,
            {
                "where": arcgis["where"],
                "outFields": "*",
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": arcgis["page_size"],
                "f": "json",
            },
        )
        batch = page.get("features", [])
        path = raw_dir / "arcgis" / f"page_{offset:06d}.json"
        path.write_text(json.dumps(page))
        features.extend(batch)
        offset += len(batch)
        if not batch or not page.get("exceededTransferLimit"):
            break
    if len(features) != expected:
        raise CountMismatch(f"ArcGIS reported {expected} wells but returned {len(features)}.")
    return features


def extract_wellhistory(
    zip_path: Path, target_apis: set[str], bounds: dict[str, float], quarantine: Quarantine
) -> tuple[list[dict[str, Any]], int, int]:
    """Return history rows for target wells, in-scope count, and total rows scanned."""
    kept: list[dict[str, Any]] = []
    scanned, in_scope = 0, 0
    seen: set[tuple] = set()
    for row in iter_rows(zip_path, "wellhistory.xml", "wellhistory"):
        if scanned == 0:
            _require_columns(row, WELLHISTORY_COLUMNS, "wellhistory")
        scanned += 1
        api = api_from_parts(row)
        if api is not None and api not in target_apis:
            continue
        in_scope += 1
        reason = wellhistory_rejection(row, bounds)
        key = (api, row.get("eff_dte"), row.get("rec_termn_dte"))
        if reason is None and key in seen:
            reason = "DUPLICATE_HISTORY_KEY"
        if reason:
            quarantine.add("wellhistory", reason, row)
            continue
        seen.add(key)
        kept.append({**row, "api": api})
    return kept, in_scope, scanned


def extract_production(
    zip_path: Path, target_apis: set[str], first: tuple[int, int], quarantine: Quarantine
) -> tuple[list[dict[str, Any]], int, int]:
    """Return target-well rows in the window. Rows are kept per completion, never allocated."""
    kept: list[dict[str, Any]] = []
    scanned, in_scope = 0, 0
    seen: set[tuple] = set()
    for row in iter_rows(zip_path, "wcproduction.xml", "wcproduction"):
        if scanned == 0:
            _require_columns(row, PRODUCTION_COLUMNS, "wcproduction")
        scanned += 1
        if scanned % 5_000_000 == 0:
            core.log(_LOG, "production scan progress", rows_scanned=scanned, kept=len(kept))
        api = api_from_parts(row)
        if (api is not None and api not in target_apis) or not _in_window(row, first):
            continue
        in_scope += 1
        reason = production_rejection(row)
        key = production_key(row)
        if reason is None and key in seen:
            reason = "DUPLICATE_CANDIDATE_KEY"
        if reason:
            quarantine.add("wcproduction", reason, row)
            continue
        seen.add(key)
        kept.append({**row, "api": api})
    return kept, in_scope, scanned


def run(
    root: Path = core.REPO_ROOT,
    refresh: bool = False,
    http: Http | None = None,
    ftp: Ftp | None = None,
    disk_usage: Any = None,
) -> dict[str, Any]:
    """Acquire one batch and return its manifest. Any failure raises before COMPLETE is written."""
    cfg = load_config(root)
    config_sha = core.config_hash(cfg)
    if not refresh and (existing := core.find_complete(root, SOURCE, config_sha)):
        core.log(_LOG, "reusing completed batch", batch_id=existing["batch_id"])
        return {**existing, "reused": True}

    http = http or Http()
    ftp = ftp or Ftp(cfg["ftp"]["host"])
    base = cfg["ftp"]["base_path"]
    remote = {name: f"{base}/{path}" for name, path in cfg["ftp"]["files"].items()}
    stats = {name: ftp.stat(path) for name, path in remote.items()}
    version = stats["wcproduction"][1][:8]
    batch_id = f"{SOURCE}-{version}-{config_sha[:10]}"
    raw_dir = root / "data" / "raw" / SOURCE / version / batch_id
    bronze_dir = root / "data" / "bronze" / SOURCE / batch_id
    if finished := core.completed_batch(root, SOURCE, batch_id):
        core.log(_LOG, "upstream version already acquired; raw is immutable", batch_id=batch_id)
        return {**finished, "reused": True}

    needed = sum(size for size, _ in stats.values())
    kwargs = {"disk_usage": disk_usage} if disk_usage else {}
    core.preflight_disk(root / "data", needed, cfg["disk_floor_bytes"], **kwargs)
    core.log(_LOG, "batch started", batch_id=batch_id, bytes_to_download=needed)

    features = fetch_well_pages(http, cfg, raw_dir)
    files: list[FileEntry] = []
    for name, path in remote.items():
        dest = raw_dir / "ftp" / Path(path).name
        size, modified = stats[name]
        if not (dest.exists() and dest.stat().st_size == size):
            core.log(_LOG, "downloading", file=path, size_bytes=size)
            ftp.download(path, dest, size, modified)
        files.append(
            FileEntry(
                path=core.rel(dest, root),
                sha256=core.sha256_file(dest),
                size_bytes=size,
                source_url=f"ftp://{cfg['ftp']['host']}{path}",
                source_modified=modified,
            )
        )
    for page in sorted((raw_dir / "arcgis").glob("*.json")):
        files.append(
            FileEntry(
                path=core.rel(page, root),
                sha256=core.sha256_file(page),
                size_bytes=page.stat().st_size,
                source_url=cfg["arcgis"]["layer_url"],
            )
        )

    quarantine = Quarantine(bronze_dir / "quarantine.jsonl")
    bounds = cfg["bounds"]
    wells = validate_wells(features, bounds["new_mexico"], quarantine)
    target_apis = {w["id"] for w in wells}
    if not target_apis:
        raise CountMismatch("No wells passed validation; refusing to continue.")

    core.log(_LOG, "parsing well history", wells=len(wells))
    history, history_scope, history_scanned = extract_wellhistory(
        raw_dir / "ftp" / "wellhistory.zip", target_apis, bounds["new_mexico"], quarantine
    )
    first = first_month_in_window(stats["wcproduction"][1], cfg["production"]["months"])
    core.log(_LOG, "parsing production", first_month=first)
    production, production_scope, production_scanned = extract_production(
        raw_dir / "ftp" / "wcproduction.zip", target_apis, first, quarantine
    )

    def stamp(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**r, "provenance_class": "OBSERVED", "source_batch_id": batch_id} for r in rows]

    extra = ["provenance_class", "source_batch_id"]
    core.write_string_parquet(bronze_dir / "wells.parquet", stamp(wells), WELL_COLUMNS + extra)
    core.write_string_parquet(
        bronze_dir / "wellhistory.parquet", stamp(history), ["api", *WELLHISTORY_COLUMNS, *extra]
    )
    core.write_string_parquet(
        bronze_dir / "wcproduction.parquet",
        stamp(production),
        ["api", *PRODUCTION_COLUMNS, *extra],
    )
    core.freeze_tree(raw_dir)

    accepted = len(wells) + len(history) + len(production)
    manifest = BatchManifest(
        batch_id=batch_id,
        source_system_id=SOURCE,
        source_version=version,
        config_sha256=config_sha,
        ingestion_timestamp=core.utc_now(),
        original_checksum=core.aggregate_checksum(files),
        source_record_count=len(features) + history_scope + production_scope,
        accepted_count=accepted,
        rejected_count=quarantine.count,
        processing_status=core.COMPLETE,
        manifest_uri=f"data/manifests/{SOURCE}/{batch_id}.json",
        license=cfg["license"],
        files=files,
        datasets={
            "wells": {"source_records": len(features), "accepted": len(wells)},
            "wellhistory": {
                "rows_scanned": history_scanned,
                "in_scope": history_scope,
                "accepted": len(history),
            },
            "wcproduction": {
                "rows_scanned": production_scanned,
                "in_scope": production_scope,
                "accepted": len(production),
                "first_month": f"{first[0]}-{first[1]:02d}",
                "reporting_grain": "well_completion (API + pool + month + product)",
                "unit_as_documented": "MCF or BBLS",
            },
            "quarantine_reasons": quarantine.reasons,
        },
        notes=[
            f"Retrieved {date.today().isoformat()}. OCD publishes no checksums and FTP is "
            "unencrypted, so SHA-256 values prove only that files are unchanged since receipt.",
            "ArcGIS is a live service with no version. Its pages reflect the retrieval date.",
        ],
    )
    core.write_manifest(manifest, root)
    core.log(
        _LOG, "batch complete", batch_id=batch_id, accepted=accepted, rejected=quarantine.count
    )
    return {**json.loads(core.manifest_path(root, SOURCE, batch_id).read_text()), "reused": False}
