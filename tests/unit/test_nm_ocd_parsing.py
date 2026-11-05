"""OCD XML streaming and record validation. Rows here are hand-written test data."""

import pandas as pd
import pytest

from pipelines.acquire.common.core import Quarantine
from pipelines.acquire.common.errors import MalformedSource
from pipelines.acquire.nm_ocd.adapter import first_month_in_window
from pipelines.acquire.nm_ocd.validate import (
    api_from_parts,
    production_key,
    production_rejection,
    validate_wells,
    wellhistory_rejection,
)
from pipelines.acquire.nm_ocd.xmlstream import iter_rows
from pipelines.profile.nm_ocd import effective_before_period
from tests.conftest import history_row, production_row, well_feature, xml_export, zipped

NM = {"lat_min": 31.3, "lat_max": 37.1, "lon_min": -109.1, "lon_max": -103.0}


def write_zip(path, rows, close_root=True):
    path.write_bytes(zipped("t.xml", xml_export("t", rows, close_root)))
    return path


def test_streams_utf16_rows_and_keeps_original_text(tmp_path):
    archive = write_zip(tmp_path / "a.zip", [{"a": "1", "kind": "G ", "gone": None, "blank": ""}])
    assert list(iter_rows(archive, "t.xml", "t")) == [
        {"a": "1", "kind": "G ", "gone": None, "blank": ""}
    ]


def test_schema_preamble_is_not_mistaken_for_a_row(tmp_path):
    archive = write_zip(tmp_path / "a.zip", [])
    assert list(iter_rows(archive, "t.xml", "t")) == []


def test_missing_closing_tag_is_malformed(tmp_path):
    archive = write_zip(tmp_path / "a.zip", [{"a": "1"}], close_root=False)
    with pytest.raises(MalformedSource):
        list(iter_rows(archive, "t.xml", "t"))


def test_broken_xml_is_malformed(tmp_path):
    archive = tmp_path / "a.zip"
    archive.write_bytes(zipped("t.xml", "<root><t><a>1</b></t></root>".encode("utf-16")))
    with pytest.raises(MalformedSource):
        list(iter_rows(archive, "t.xml", "t"))


def test_truncated_zip_is_malformed(tmp_path):
    archive = write_zip(tmp_path / "a.zip", [{"a": str(i)} for i in range(5000)])
    archive.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
    with pytest.raises(MalformedSource):
        list(iter_rows(archive, "t.xml", "t"))


def test_missing_member_is_malformed(tmp_path):
    archive = write_zip(tmp_path / "a.zip", [])
    with pytest.raises(MalformedSource):
        list(iter_rows(archive, "other.xml", "t"))


def test_api_number_is_built_from_ocd_parts():
    assert api_from_parts(production_row()) == "30-015-90001"
    assert api_from_parts(production_row(api_well_idn=None)) is None


def test_production_window_counts_back_from_file_date():
    assert first_month_in_window("20261105012200", 36) == (2023, 12)
    assert first_month_in_window("20260105012200", 1) == (2026, 1)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"pool_idn": None}, "MISSING_KEY_FIELD"),
        ({"prodn_mth": "13"}, "INVALID_PERIOD"),
        ({"prodn_yr": "abc"}, "INVALID_PERIOD"),
        ({"prd_knd_cde": "Z "}, "UNKNOWN_PRODUCT_KIND"),
        ({"prod_amt": "-5"}, "NEGATIVE_VOLUME"),
        ({"prod_amt": "ten"}, "NON_NUMERIC_VOLUME"),
    ],
)
def test_invalid_production_rows_are_rejected(change, reason):
    assert production_rejection(production_row(**change)) == reason


def test_valid_production_row_passes_and_null_volume_is_not_invented():
    assert production_rejection(production_row()) is None
    assert production_rejection(production_row(prod_amt=None)) is None


def test_amended_rows_with_a_new_effective_date_are_distinct_keys():
    original = production_row()
    amended = production_row(eff_dte="2026-07-31T00:00:00", amend_ind="Y")
    assert production_key(original) != production_key(amended)


def test_contradictory_history_timestamps_are_rejected():
    row = history_row(eff_dte="2024-01-01T00:00:00", rec_termn_dte="2020-01-01T00:00:00")
    assert wellhistory_rejection(row, NM) == "CONTRADICTORY_TIMESTAMPS"


def test_open_ended_history_sentinel_is_not_contradictory():
    assert wellhistory_rejection(history_row(), NM) is None


def test_history_coordinates_are_checked():
    assert wellhistory_rejection(history_row(latitude="99.0"), NM) == "INVALID_COORDINATES"


@pytest.mark.parametrize(
    ("attributes", "reason"),
    [
        ({"latitude": 91.0}, "INVALID_COORDINATES"),
        ({"longitude": None}, "INVALID_COORDINATES"),
        ({"latitude": 0.0, "longitude": 0.0}, "INVALID_COORDINATES"),
    ],
)
def test_invalid_well_coordinates_are_quarantined(tmp_path, attributes, reason):
    quarantine = Quarantine(tmp_path / "q.jsonl")
    assert validate_wells([well_feature(**attributes)], NM, quarantine) == []
    assert quarantine.reasons == {f"wells:{reason}": 1}


def test_malformed_api_is_quarantined(tmp_path):
    quarantine = Quarantine(tmp_path / "q.jsonl")
    assert validate_wells([well_feature(api="42-015-90001")], NM, quarantine) == []
    assert quarantine.reasons == {"wells:INVALID_API": 1}


def test_conflicting_duplicate_wells_are_both_quarantined(tmp_path):
    quarantine = Quarantine(tmp_path / "q.jsonl")
    features = [well_feature(status="Active"), well_feature(status="Plugged", OBJECTID=2)]
    assert validate_wells(features, NM, quarantine) == []
    assert quarantine.reasons == {"wells:DUPLICATE_API_CONFLICTING": 2}


def test_identical_duplicate_keeps_one_and_records_the_other(tmp_path):
    quarantine = Quarantine(tmp_path / "q.jsonl")
    features = [well_feature(), well_feature(OBJECTID=2)]
    assert len(validate_wells(features, NM, quarantine)) == 1
    assert quarantine.reasons == {"wells:DUPLICATE_API_IDENTICAL": 1}


def periods_frame(*dates):
    return pd.DataFrame({"eff_dte": dates, "prodn_yr": "2023", "prodn_mth": "12"})


def test_filing_after_the_production_month_is_not_an_anomaly():
    # Real shape from OCD: mixed precision, which default date inference silently turns into NaT.
    frame = periods_frame("2024-02-08T19:00:31.220", "2024-02-14T19:00:49")
    assert effective_before_period(frame).tolist() == [False, False]


def test_effective_date_before_the_production_month_is_flagged():
    assert effective_before_period(periods_frame("2023-11-30T00:00:00")).tolist() == [True]


def test_unparseable_effective_date_raises_instead_of_passing():
    with pytest.raises(ValueError):
        effective_before_period(periods_frame("not-a-date"))
