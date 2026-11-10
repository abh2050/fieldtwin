"""Registry wells that may enter spatial analysis, decided by the Gate 2 coordinate rules."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from packages.domain.models import SpatialStatus, well_id
from packages.inspection.association import Points
from pipelines.acquire.common import core
from pipelines.normalize import spatial_rules
from pipelines.normalize.ocd import OPEN_ENDED


def latest_batch(root: Path, source: str) -> dict:
    manifests = [
        m for m in core.load_manifests(root, source) if m["processing_status"] == "COMPLETE"
    ]
    if not manifests:
        raise FileNotFoundError(f"No completed {source} batch. Run `make acquire` first.")
    return max(manifests, key=lambda m: m["ingestion_timestamp"])


def registry_wells(root: Path) -> tuple[pd.DataFrame, str]:
    """All registry wells with their Gate 2 spatial status, and the OCD batch ID used."""
    batch = latest_batch(root, "nm_ocd")["batch_id"]
    bronze = root / "data" / "bronze" / "nm_ocd" / batch
    wells = pd.read_parquet(bronze / "wells.parquet").to_dict("records")
    history = pd.read_parquet(bronze / "wellhistory.parquet").to_dict("records")
    open_history = {
        h["api"]: h for h in history if (h.get("rec_termn_dte") or "").startswith(OPEN_ENDED)
    }
    outliers = spatial_rules.plss_peer_outliers(wells)
    rows = []
    for well in wells:
        ftp_datum = (open_history.get(well["id"]) or {}).get("datum")
        status = spatial_rules.spatial_status(
            well["id"] in outliers, spatial_rules.datum_finding(well.get("projection"), ftp_datum)
        )
        rows.append(
            {
                "source_asset_id": well_id(well["id"]),
                "latitude": float(well["latitude"]),
                "longitude": float(well["longitude"]),
                "spatial_status": status.value,
            }
        )
    return pd.DataFrame(rows).sort_values("source_asset_id", ignore_index=True), batch


def usable_points(frame: pd.DataFrame) -> Points:
    usable = frame[frame["spatial_status"] == SpatialStatus.USABLE.value]
    return Points.of(
        usable["source_asset_id"].tolist(),
        usable["latitude"].tolist(),
        usable["longitude"].tolist(),
    )
