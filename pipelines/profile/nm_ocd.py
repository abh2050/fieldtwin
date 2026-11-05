"""Profile the OCD batch and cross-check its independent systems (ArcGIS against FTP extracts)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd
import pandera.pandas as pa

from pipelines.acquire.common.core import load_yaml
from pipelines.acquire.nm_ocd.adapter import SOURCE
from pipelines.normalize.spatial_rules import plss_peer_outliers

from .common import FAIL, PASS, WARN, Check, latest_complete, threshold, write_report, zero_expected

WELL_SCHEMA = pa.DataFrameSchema(
    {
        "id": pa.Column(str, pa.Check.str_matches(r"^30-015-\d{5}$"), unique=True),
        "type": pa.Column(str, pa.Check.eq("Gas")),
        "county": pa.Column(str, pa.Check.eq("Eddy")),
        "ulstr": pa.Column(str, pa.Check.str_contains(r"-2[34]S-28E$")),
        "provenance_class": pa.Column(str, pa.Check.eq("OBSERVED")),
    },
    strict=False,
)
PRODUCTION_SCHEMA = pa.DataFrameSchema(
    {
        "api": pa.Column(str, pa.Check.str_matches(r"^30-015-\d{5}$")),
        "pool_idn": pa.Column(str),
        "prodn_mth": pa.Column(str, pa.Check.str_matches(r"^([1-9]|1[0-2])$")),
        "prodn_yr": pa.Column(str, pa.Check.str_matches(r"^\d{4}$")),
        "prd_knd_cde": pa.Column(str, pa.Check.str_matches(r"^[OGW] *$")),
        "provenance_class": pa.Column(str, pa.Check.eq("OBSERVED")),
    },
    strict=False,
)


PERIOD_KEY = ["api", "pool_idn", "prodn_yr", "prodn_mth", "prd_knd_cde"]


def _schema_check(name: str, schema: pa.DataFrameSchema, frame: pd.DataFrame) -> Check:
    try:
        schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        return Check(name, FAIL, len(exc.failure_cases), "Pandera schema has no failure cases")
    return Check(name, PASS, 0, "Pandera schema has no failure cases")


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle metres. Adequate for comparing two coordinates of the same well."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def effective_before_period(production: pd.DataFrame) -> pd.Series:
    """True where eff_dte precedes the production month. Unparseable dates raise, not vanish."""
    effective = pd.to_datetime(production["eff_dte"], format="ISO8601")
    start = pd.to_datetime(
        dict(
            year=production["prodn_yr"].astype(int),
            month=production["prodn_mth"].astype(int),
            day=1,
        )
    )
    return effective < start


def status_codes(dictionary_path: Path) -> dict[str, str]:
    """Read OCD's own decode table for wellhistory status codes."""
    workbook = openpyxl.load_workbook(dictionary_path, read_only=True, data_only=True)
    return {
        str(row[3]).strip(): str(row[4]).strip()
        for row in workbook["consolidated code list"].iter_rows(values_only=True)
        if row[1] == "wellhistory" and row[2] == "status"
    }


def profile(root: Path) -> Path:
    manifest = latest_complete(root, SOURCE)
    batch_id = manifest["batch_id"]
    bronze = root / "data" / "bronze" / SOURCE / batch_id
    raw = root / "data" / "raw" / SOURCE / manifest["source_version"] / batch_id
    config = load_yaml(root / "config" / "sources" / "nm_ocd.yaml")

    wells = pd.read_parquet(bronze / "wells.parquet")
    history = pd.read_parquet(bronze / "wellhistory.parquet")
    production = pd.read_parquet(bronze / "wcproduction.parquet")
    checks: list[Check] = [
        _schema_check("wells_schema", WELL_SCHEMA, wells),
        _schema_check("production_schema", PRODUCTION_SCHEMA, production),
        zero_expected("wells_duplicate_api", wells["id"].duplicated().sum(), "No duplicate API"),
    ]

    target = config["arcgis"]
    checks.append(
        Check(
            "wells_in_target_range",
            PASS if target["min_records"] <= len(wells) <= target["max_records"] else FAIL,
            len(wells),
            f"{target['min_records']}-{target['max_records']} accepted wells",
        )
    )

    lat, lon = wells["latitude"].astype(float), wells["longitude"].astype(float)
    box = config["bounds"]["eddy_county_approx"]
    outside = ~(
        lat.between(box["lat_min"], box["lat_max"]) & lon.between(box["lon_min"], box["lon_max"])
    )
    # Zero tolerance: every coordinate outside the box must be caught by a quarantine rule.
    records = wells[["id", "ulstr", "latitude", "longitude"]].to_dict("records")
    quarantined = set(plss_peer_outliers(records))
    unquarantined = set(wells.loc[outside, "id"]) - quarantined
    checks.append(
        zero_expected(
            "wells_outside_eddy_box_raw",
            outside.sum(),
            "Inside approximate box (raw count, before quarantine)",
            severity=WARN,
        )
    )
    checks.append(
        zero_expected(
            "wells_outside_eddy_box_not_quarantined",
            len(unquarantined),
            "Any well outside the box must be excluded by the spatial quarantine rule",
        )
    )
    # Identifying details stay in the local database. This report is published.
    coordinate_outlier_count = int(outside.sum())

    # Cross-system consistency: FTP well history against the ArcGIS registry, joined on API only.
    # Both are OCD systems, so agreement shows consistent delivery, not independent ground truth.
    current = history[history["rec_termn_dte"].fillna("").str.startswith("9999")]
    target_apis = set(wells["id"])
    found = target_apis & set(history["api"])
    checks.append(
        threshold(
            "registry_wells_in_ftp_history",
            len(found) / len(target_apis),
            0.99,
            "PASS at 99%+ of ArcGIS wells present in wellhistory",
        )
    )
    open_counts = current.groupby("api").size()
    checks.append(
        Check(
            "wells_with_multiple_open_history_rows",
            PASS if (open_counts > 1).sum() == 0 else WARN,
            int((open_counts > 1).sum()),
            "Each well has at most one open (9999-12-31) history row",
        )
    )

    latest = current.drop_duplicates("api")
    joined = wells.merge(latest, left_on="id", right_on="api", suffixes=("", "_ftp"))
    codes = status_codes(raw / "ftp" / "OCD Interface v1.1 Data Dictionary.xlsx")
    decoded = joined["status_ftp"].str.strip().map(codes)
    checks.append(
        threshold(
            "status_agreement",
            float((decoded == joined["status"]).mean()),
            0.95,
            "PASS at 95%+ of wells with the same status after OCD's decode table",
        )
    )
    checks.append(
        threshold(
            "operator_agreement",
            float((joined["ogrid"] == joined["ogrid_cde"]).mean()),
            0.90,
            "PASS at 90%+ of wells with the same OGRID in both systems",
        )
    )

    datum_pairs = (
        joined["projection"].fillna("").str.strip() + "|" + joined["datum"].fillna("").str.strip()
    )
    conflicting = (
        joined["projection"].fillna("").str.strip() != joined["datum"].fillna("").str.strip()
    )
    checks.append(
        zero_expected(
            "datum_label_conflicts_across_systems",
            conflicting.sum(),
            "ArcGIS projection and FTP datum name the same datum",
            severity=WARN,
        )
    )

    located = joined.dropna(subset=["latitude_ftp", "longitude_ftp"])
    distances = pd.Series(
        [
            _distance_m(float(a), float(b), float(c), float(d))
            for a, b, c, d in zip(
                located["latitude"],
                located["longitude"],
                located["latitude_ftp"],
                located["longitude_ftp"],
                strict=True,
            )
        ],
        dtype=float,
    )
    checks.append(
        threshold(
            "coordinates_within_100m_across_systems",
            float((distances <= 100).mean()) if len(distances) else 0.0,
            0.95,
            "PASS at 95%+ of wells within 100 m between ArcGIS and wellhistory",
        )
    )

    # Does production exist for the wells that should have it?
    produced = set(production["api"])
    wells["has_production"] = wells["id"].isin(produced)
    coverage = (
        wells.groupby("status")["has_production"]
        .agg(["size", "sum"])
        .rename(columns={"size": "wells", "sum": "with_production_in_window"})
    )
    active = wells[wells["status"] == "Active"]
    checks.append(
        threshold(
            "active_wells_with_production",
            float(active["has_production"].mean()) if len(active) else 0.0,
            0.90,
            "PASS at 90%+ of Active wells with a production row in the window",
        )
    )
    checks.append(
        Check(
            "production_rows_outside_target_wells",
            PASS if produced <= target_apis else FAIL,
            len(produced - target_apis),
            "Every production row belongs to a target well",
        )
    )

    # Consistency: ArcGIS last_production_date against the FTP production months.
    periods = pd.to_datetime(
        dict(
            year=production["prodn_yr"].astype(int),
            month=production["prodn_mth"].astype(int),
            day=1,
        )
    )
    last_ftp = periods.groupby(production["api"]).max()
    last_arcgis = pd.to_datetime(
        pd.to_numeric(wells.set_index("id")["last_production_date"], errors="coerce"),
        unit="ms",
        errors="coerce",
    )
    both = pd.concat([last_ftp.rename("ftp"), last_arcgis.rename("arcgis")], axis=1, join="inner")
    both = both[both["arcgis"].dt.year.between(2000, 2100)]
    within = ((both["ftp"] - both["arcgis"]).abs() <= pd.Timedelta(days=62)).mean()
    checks.append(
        threshold(
            "last_production_month_agreement",
            float(within) if len(both) else 0.0,
            0.90,
            "PASS at 90%+ of wells within two months between systems",
        )
    )

    # Timestamp and value anomalies. Reported, because the source may legitimately contain them.
    days = pd.to_numeric(production["prodn_day_num"], errors="coerce")
    checks += [
        zero_expected(
            "production_effective_date_before_period",
            effective_before_period(production).sum(),
            "eff_dte, a filing time in recent rows, is not before the production month",
            severity=WARN,
        ),
        zero_expected(
            "production_periods_with_multiple_rows",
            production.duplicated(PERIOD_KEY).sum(),
            "One row per completion, month, and product, so volumes cannot double count",
        ),
        zero_expected(
            "production_days_over_31",
            (days > 31).sum(),
            "prodn_day_num is 31 or less",
            severity=WARN,
        ),
        zero_expected(
            "quarantined_records",
            manifest["rejected_count"],
            "No records quarantined",
            severity=WARN,
        ),
    ]

    non_nad83 = wells["projection"].fillna("").str.strip().value_counts().to_dict()
    month_rows = periods.value_counts().sort_index()
    partial_months = month_rows[month_rows < month_rows.median() * 0.5]
    report: dict[str, Any] = {
        "batch_id": batch_id,
        "provenance_class": "OBSERVED",
        "record_counts": {
            "wells": len(wells),
            "wellhistory_rows": len(history),
            "production_rows": len(production),
            "production_wells": len(produced),
            "production_completions": int(
                production[["api", "pool_idn"]].drop_duplicates().shape[0]
            ),
        },
        "wells_by_status": wells["status"].value_counts().to_dict(),
        "production_coverage_by_status": coverage.reset_index().to_dict("records"),
        "validation_scope": (
            "ArcGIS and FTP are both OCD systems and carry identical values. Agreement shows "
            "consistent delivery from one source of record, not independent confirmation."
        ),
        "coordinate_outlier_count": coordinate_outlier_count,
        "coordinate_datum_counts": non_nad83,
        "datum_label_pairs_arcgis_vs_ftp": datum_pairs.value_counts().to_dict(),
        "partial_recent_months": {str(k.date()): int(v) for k, v in partial_months.items()},
        "production_period": {
            "first": str(periods.min().date()),
            "last": str(periods.max().date()),
        },
        "production_rows_by_month": {
            str(k.date()): int(v) for k, v in periods.value_counts().sort_index().items()
        },
        "production_rows_by_kind": production["prd_knd_cde"].str.strip().value_counts().to_dict(),
        "production_amount_null_rate": round(float(production["prod_amt"].isna().mean()), 4),
        "amended_rows": production["amend_ind"].value_counts(dropna=False).to_dict(),
        "cross_system_distance_m": {
            k: round(float(v), 1)
            for k, v in distances.describe(percentiles=[0.5, 0.95]).items()
            if k != "count"
        },
        "null_rates": {
            "wells": wells.isna().mean().round(4).to_dict(),
            "production": production.isna().mean().round(4).to_dict(),
        },
        "quarantine_reasons": manifest["datasets"].get("quarantine_reasons", {}),
    }
    return write_report(root, SOURCE, report, checks)
