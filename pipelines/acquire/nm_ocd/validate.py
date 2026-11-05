"""Record-level checks for OCD data. Failures go to quarantine with a reason."""

from __future__ import annotations

import re
from typing import Any

from pipelines.acquire.common.core import Quarantine

API_PATTERN = re.compile(r"^30-\d{3}-\d{5}$")
PRODUCT_KINDS = {"O", "G", "W"}


def api_from_parts(row: dict[str, Any]) -> str | None:
    """Build the API number from OCD's split columns, the identifier both OCD systems share."""
    try:
        state = int(row["api_st_cde"])
        county = int(row["api_cnty_cde"])
        well = int(row["api_well_idn"])
    except (KeyError, TypeError, ValueError):
        return None
    return f"{state:02d}-{county:03d}-{well:05d}"


def _in_bounds(lat: Any, lon: Any, bounds: dict[str, float]) -> bool:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return (
        bounds["lat_min"] <= lat <= bounds["lat_max"]
        and bounds["lon_min"] <= lon <= bounds["lon_max"]
    )


def validate_wells(
    features: list[dict[str, Any]], bounds: dict[str, float], quarantine: Quarantine
) -> list[dict[str, Any]]:
    """Flatten ArcGIS features. Conflicting duplicates are all quarantined; neither is trusted."""
    by_api: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        geometry = feature.get("geometry") or {}
        row = {
            **feature.get("attributes", {}),
            "geometry_x": geometry.get("x"),
            "geometry_y": geometry.get("y"),
        }
        api = row.get("id")
        if not api or not API_PATTERN.match(str(api)):
            quarantine.add("wells", "INVALID_API", row)
        elif not _in_bounds(row.get("latitude"), row.get("longitude"), bounds):
            quarantine.add("wells", "INVALID_COORDINATES", row)
        else:
            by_api.setdefault(api, []).append(row)

    accepted = []
    for rows in by_api.values():
        comparable = [{k: v for k, v in r.items() if k != "OBJECTID"} for r in rows]
        if len(rows) == 1 or all(c == comparable[0] for c in comparable):
            accepted.append(rows[0])
            for extra in rows[1:]:
                quarantine.add("wells", "DUPLICATE_API_IDENTICAL", extra)
        else:
            for row in rows:
                quarantine.add("wells", "DUPLICATE_API_CONFLICTING", row)
    return accepted


def production_rejection(row: dict[str, str | None]) -> str | None:
    """Return why a production row is invalid, or None. Volume units are left as reported."""
    required = (
        "api_st_cde", "api_cnty_cde", "api_well_idn", "pool_idn", "prodn_mth", "prodn_yr",
        "ogrid_cde", "prd_knd_cde", "eff_dte",
    )  # fmt: skip
    if any(row.get(column) in (None, "") for column in required):
        return "MISSING_KEY_FIELD"
    try:
        month, year = int(str(row["prodn_mth"])), int(str(row["prodn_yr"]))
    except ValueError:
        return "INVALID_PERIOD"
    if not (1 <= month <= 12 and 1900 <= year <= 2100):
        return "INVALID_PERIOD"
    if str(row["prd_knd_cde"]).strip() not in PRODUCT_KINDS:
        return "UNKNOWN_PRODUCT_KIND"
    amount = row.get("prod_amt")
    if amount is not None:
        try:
            if int(amount) < 0:
                return "NEGATIVE_VOLUME"
        except ValueError:
            return "NON_NUMERIC_VOLUME"
    return None


def production_key(row: dict[str, str | None]) -> tuple:
    """The candidate key from the OCD data dictionary."""
    return tuple(
        row.get(c)
        for c in (
            "api_st_cde", "api_cnty_cde", "api_well_idn", "pool_idn", "prodn_mth", "prodn_yr",
            "ogrid_cde", "prd_knd_cde", "eff_dte",
        )
    )  # fmt: skip


def wellhistory_rejection(row: dict[str, str | None], bounds: dict[str, float]) -> str | None:
    """Return why a well-history row is invalid, or None."""
    if api_from_parts(row) is None:
        return "INVALID_API"
    start, end = row.get("eff_dte"), row.get("rec_termn_dte")
    # ISO timestamps sort as text. 9999-12-31 is OCD's open-ended sentinel, so it sorts last.
    if start and end and start > end:
        return "CONTRADICTORY_TIMESTAMPS"
    lat, lon = row.get("latitude"), row.get("longitude")
    if lat is not None and lon is not None and not _in_bounds(lat, lon, bounds):
        return "INVALID_COORDINATES"
    return None
