"""Normalize OCD bronze data into canonical records. Pure functions; loading happens in load.py."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from packages.domain.models import (
    DataQualityException,
    HistoryRecord,
    ProductionRecord,
    ReconciliationEvidence,
    SourceAsset,
    SpatialStatus,
    completion_id,
    well_id,
)
from packages.domain.semantics import AmbiguousUnitError, resolve_production_unit

from . import spatial_rules

SOURCE = "nm_ocd"
WELL_CLASS = "NM_ONSHORE_WELL"
OPEN_ENDED = "9999-12-31"
ARCGIS, FTP = "ocd_arcgis_wells_public", "ocd_ftp_wellhistory"
RECONCILIATION_METHOD = "ocd-arcgis-vs-ftp@1"
T_WELL = "ocd.arcgis_wells.to_source_assets@1"
T_COMPLETION = "ocd.production_keys.to_completions@1"
T_HISTORY = "ocd.wellhistory.to_history@1"
T_PRODUCTION = "ocd.wcproduction.to_production_records@1"


@dataclass
class OcdCanonical:
    wells: list[SourceAsset] = field(default_factory=list)
    completions: list[SourceAsset] = field(default_factory=list)
    history: list[HistoryRecord] = field(default_factory=list)
    production: list[ProductionRecord] = field(default_factory=list)
    exceptions: list[DataQualityException] = field(default_factory=list)
    evidence: list[ReconciliationEvidence] = field(default_factory=list)


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    """Turn pandas missing values back into None. Text is otherwise untouched."""
    return {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in row.items()}


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_clean(r) for r in frame.to_dict("records")]


def _date(text: str | None) -> date | None:
    return datetime.fromisoformat(text).date() if text else None


def _stripped(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _coordinate(value: Any) -> float | None:
    return None if value is None else float(value)


def _within_metres(a: dict[str, Any], b: dict[str, Any] | None, limit: float = 1.0) -> bool:
    if b is None or b.get("latitude") is None or b.get("longitude") is None:
        return False
    distance = spatial_rules.distance_km(
        float(a["latitude"]), float(a["longitude"]), float(b["latitude"]), float(b["longitude"])
    )
    return distance * 1000 <= limit


def normalize_wells(
    wells: list[dict[str, Any]],
    open_history: dict[str, dict[str, Any]],
    status_decode: dict[str, str],
    bounds: dict[str, float],
    batch_id: str,
) -> tuple[list[SourceAsset], list[DataQualityException], list[ReconciliationEvidence]]:
    outliers = spatial_rules.plss_peer_outliers(wells)
    assets, exceptions, evidence = [], [], []

    def compare(asset_id: str, name: str, a: Any, b: Any, agree: bool | None = None) -> None:
        if a in (None, "") or b in (None, ""):
            outcome = "MISSING"
        else:
            same = str(a).strip() == str(b).strip() if agree is None else agree
            outcome = "AGREE" if same else "CONFLICT"
        evidence.append(
            ReconciliationEvidence(
                source_asset_id=asset_id,
                batch_id=batch_id,
                field_name=name,
                channel_a=ARCGIS,
                value_a=None if a is None else str(a),
                channel_b=FTP,
                value_b=None if b is None else str(b),
                outcome=outcome,
                channels_are_independent=False,
                method_version=RECONCILIATION_METHOD,
            )
        )

    for well in wells:
        api = well["id"]
        asset_id = well_id(api)
        history = open_history.get(api)
        ftp_datum = history.get("datum") if history else None
        datum_rule = spatial_rules.datum_finding(well.get("projection"), ftp_datum)
        status = spatial_rules.spatial_status(api in outliers, datum_rule)
        reported = {
            "latitude": well["latitude"],
            "longitude": well["longitude"],
            "ulstr": well.get("ulstr"),
            "arcgis_projection": well.get("projection"),
            "ftp_datum": ftp_datum,
        }

        assets.append(
            SourceAsset(
                source_asset_id=asset_id,
                source_system_id=SOURCE,
                asset_type="WELL",
                external_identifier=api,
                asset_name=well.get("name"),
                equipment_class_id=WELL_CLASS,
                operating_status=well.get("status"),
                reported_latitude=_coordinate(well["latitude"]),
                reported_longitude=_coordinate(well["longitude"]),
                reported_datum_label=_stripped(well.get("projection")),
                spatial_status=status,
                attributes=well,
                batch_id=batch_id,
                transformation_id=T_WELL,
                source_record_key=f"OBJECTID={well['OBJECTID']}",
            )
        )

        if api in outliers:
            lat, lon = float(well["latitude"]), float(well["longitude"])
            in_box = (
                bounds["lat_min"] <= lat <= bounds["lat_max"]
                and bounds["lon_min"] <= lon <= bounds["lon_max"]
            )
            same_in_both = _within_metres(well, history)
            exceptions.append(
                DataQualityException(
                    exception_type="COORDINATE_INCONSISTENT_WITH_PLSS",
                    severity="ERROR",
                    source_system_id=SOURCE,
                    batch_id=batch_id,
                    dataset="wells",
                    source_asset_id=asset_id,
                    source_record_key=api,
                    field_name="latitude,longitude",
                    original_values=reported,
                    evidence={
                        **outliers[api],
                        "inside_county_box": in_box,
                        "same_value_in_arcgis_and_ftp": same_in_both,
                    },
                    rule_id=spatial_rules.PEER_RULE,
                    disposition="QUARANTINED_FROM_SPATIAL",
                    status="OPEN",
                    decision_rationale=(
                        "Coordinate contradicts the well's reported township. It stays out of "
                        "spatial analytics until OCD data shows a correction. The reported value "
                        "is kept and no corrected value is assumed."
                    ),
                )
            )
        if datum_rule:
            conflict = datum_rule == spatial_rules.DATUM_CONFLICT_RULE
            exceptions.append(
                DataQualityException(
                    exception_type="DATUM_LABEL_CONFLICT" if conflict else "DATUM_LABEL_MISSING",
                    severity="WARNING",
                    source_system_id=SOURCE,
                    batch_id=batch_id,
                    dataset="wells",
                    source_asset_id=asset_id,
                    source_record_key=api,
                    field_name="projection,datum",
                    original_values=reported,
                    evidence={"coordinates_match_across_channels": _within_metres(well, history)},
                    rule_id=datum_rule,
                    disposition="FLAGGED_UNRESOLVED",
                    status="OPEN",
                    decision_rationale=(
                        "The two OCD channels don't both name one datum for these coordinates. "
                        "The datum isn't guessed, so no analytic geometry is created."
                    ),
                )
            )

        if history:
            decoded = status_decode.get((history.get("status") or "").strip())
            compare(asset_id, "status", well.get("status"), decoded)
            compare(asset_id, "operator_code", well.get("ogrid"), history.get("ogrid_cde"))
            compare(
                asset_id,
                "coordinates",
                f"{well['latitude']},{well['longitude']}",
                f"{history.get('latitude')},{history.get('longitude')}",
                agree=_within_metres(well, history),
            )
            compare(asset_id, "datum_label", well.get("projection"), ftp_datum)
        else:
            compare(asset_id, "record_present", api, None)
    return assets, exceptions, evidence


def normalize_history(rows: list[dict[str, Any]], batch_id: str) -> list[HistoryRecord]:
    records = []
    for row in rows:
        valid_to = _date(row["rec_termn_dte"])
        records.append(
            HistoryRecord(
                source_asset_id=well_id(row["api"]),
                valid_from=datetime.fromisoformat(row["eff_dte"]).date(),
                valid_to=None if str(valid_to) == OPEN_ENDED else valid_to,
                operator_code=row.get("ogrid_cde"),
                status_code=_stripped(row.get("status")),
                well_type_code=_stripped(row.get("well_typ_cde")),
                reported_latitude=_coordinate(row.get("latitude")),
                reported_longitude=_coordinate(row.get("longitude")),
                reported_datum_label=_stripped(row.get("datum")),
                attributes=row,
                batch_id=batch_id,
                transformation_id=T_HISTORY,
                source_record_key=f"{row['api']}|{row['eff_dte']}|{row['rec_termn_dte']}",
            )
        )
    return records


def normalize_production(
    rows: list[dict[str, Any]],
    unit_rules: dict[str, str],
    unit_system: str,
    grain: str,
    raw_uri: str,
    batch_id: str,
) -> tuple[list[SourceAsset], list[ProductionRecord], list[DataQualityException]]:
    """Attach verified units. A row with no verified unit is excluded and recorded, never guessed."""
    completions: dict[str, SourceAsset] = {}
    records, exceptions = [], []
    for row in rows:
        api, pool = row["api"], row["pool_idn"]
        key = "|".join(
            str(row[c])
            for c in (
                "api",
                "pool_idn",
                "prodn_yr",
                "prodn_mth",
                "ogrid_cde",
                "prd_knd_cde",
                "eff_dte",
            )
        )
        entity = completion_id(api, pool)
        try:
            unit = resolve_production_unit(row.get("prd_knd_cde"), unit_rules)
        except AmbiguousUnitError as exc:
            exceptions.append(
                DataQualityException(
                    exception_type="AMBIGUOUS_PRODUCTION_UNIT",
                    severity="ERROR",
                    source_system_id=SOURCE,
                    batch_id=batch_id,
                    dataset="wcproduction",
                    source_asset_id=well_id(api),
                    source_record_key=key,
                    field_name="prd_knd_cde",
                    original_values=row,
                    evidence={"error": str(exc)},
                    rule_id="PRODUCTION-UNIT-VERIFIED-1",
                    disposition="QUARANTINED_RECORD",
                    status="OPEN",
                    decision_rationale="No verified unit exists for this product kind, so the row is not loaded.",
                )
            )
            continue
        completions.setdefault(
            entity,
            SourceAsset(
                source_asset_id=entity,
                source_system_id=SOURCE,
                parent_source_asset_id=well_id(api),
                asset_type="WELL_COMPLETION",
                external_identifier=f"{api}:{pool}",
                equipment_class_id=WELL_CLASS,
                spatial_status=SpatialStatus.NO_LOCATION,
                batch_id=batch_id,
                transformation_id=T_COMPLETION,
                source_record_key=f"{api}|{pool}",
            ),
        )
        modified = row.get("mod_dte")
        amended = row.get("amend_ind")
        records.append(
            ProductionRecord(
                source_system_id=SOURCE,
                reporting_entity_id=entity,
                reporting_grain=grain,
                reporting_period=date(int(row["prodn_yr"]), int(row["prodn_mth"]), 1),
                product_kind=row["prd_knd_cde"].strip(),
                reported_volume=None if row.get("prod_amt") is None else int(row["prod_amt"]),
                unit_id=unit,
                unit_system=unit_system,
                pool_code=pool,
                operator_code=row["ogrid_cde"],
                days_produced=None
                if row.get("prodn_day_num") is None
                else int(row["prodn_day_num"]),
                completion_status_code=_stripped(row.get("c115_wc_stat_cde")),
                is_amended=None if amended is None else amended.strip() == "Y",
                source_effective_at=datetime.fromisoformat(row["eff_dte"]),
                source_modified_at=datetime.fromisoformat(modified) if modified else None,
                original_record_uri=raw_uri,
                batch_id=batch_id,
                transformation_id=T_PRODUCTION,
                source_record_key=key,
            )
        )
    return list(completions.values()), records, exceptions


def quarantine_to_exceptions(
    path: Path, batch_id: str, known_apis: set[str]
) -> list[DataQualityException]:
    """Carry acquisition quarantine into the database, so those rows stay visible."""
    if not path.exists():
        return []
    exceptions = []
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        row = entry["record"]
        key = "|".join(
            str(row.get(c))
            for c in (
                "api_st_cde",
                "api_cnty_cde",
                "api_well_idn",
                "eff_dte",
                "rec_termn_dte",
                "id",
            )
        )
        api = None
        if row.get("api_well_idn"):
            api = f"{int(row['api_st_cde']):02d}-{int(row['api_cnty_cde']):03d}-{int(row['api_well_idn']):05d}"
        elif row.get("id"):
            api = row["id"]
        exceptions.append(
            DataQualityException(
                exception_type=f"ACQUISITION_{entry['reason']}",
                severity="WARNING",
                source_system_id=SOURCE,
                batch_id=batch_id,
                dataset=entry["dataset"],
                source_asset_id=well_id(api) if api in known_apis else None,
                source_record_key=key,
                original_values=row,
                evidence={"quarantined_by": "pipelines/acquire/nm_ocd/validate.py"},
                rule_id=f"ACQUIRE-{entry['reason']}",
                disposition="QUARANTINED_RECORD",
                status="ACCEPTED",
                decision_rationale="Failed validation at acquisition. Kept here with its original values and not loaded.",
            )
        )
    return exceptions


def normalize_batch(
    wells_frame: pd.DataFrame,
    history_frame: pd.DataFrame,
    production_frame: pd.DataFrame,
    quarantine_path: Path,
    status_decode: dict[str, str],
    unit_rules: dict[str, str],
    unit_system: str,
    grain: str,
    production_uri: str,
    bounds: dict[str, float],
    batch_id: str,
) -> OcdCanonical:
    source_columns = ["provenance_class", "source_batch_id"]
    wells = _records(wells_frame.drop(columns=source_columns))
    history = _records(history_frame.drop(columns=source_columns))
    production = _records(production_frame.drop(columns=source_columns))
    open_history = {
        r["api"]: r for r in history if (r.get("rec_termn_dte") or "").startswith(OPEN_ENDED)
    }
    result = OcdCanonical()
    result.wells, well_exceptions, result.evidence = normalize_wells(
        wells, open_history, status_decode, bounds, batch_id
    )
    result.history = normalize_history(history, batch_id)
    result.completions, result.production, unit_exceptions = normalize_production(
        production, unit_rules, unit_system, grain, production_uri, batch_id
    )
    known = {w["id"] for w in wells}
    result.exceptions = (
        well_exceptions
        + unit_exceptions
        + quarantine_to_exceptions(quarantine_path, batch_id, known)
    )
    return result
