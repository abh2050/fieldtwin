"""Semantic rules, domain contracts, and normalization, with no database."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from packages.domain import models
from packages.domain.models import CompatibilityClass, ProvenanceClass, ReferenceType, SpatialStatus
from packages.domain.semantics import (
    AmbiguousUnitError,
    Conversion,
    SemanticError,
    Unit,
    check_pressure_reference,
    check_tag_mapping,
    is_mappable,
    resolve_production_unit,
)
from pipelines.normalize import ocd, petrobras_3w, spatial_rules
from pipelines.normalize.seed import build_assessments, build_semantics
from tests.conftest import CI_WORKSPACE, REPO_ROOT

CONTRACTS = REPO_ROOT / "data_contracts" / "semantic_mappings"
COMPATIBILITY = yaml.safe_load((CONTRACTS / "3w_aether_compatibility.yaml").read_text())
UNITS = yaml.safe_load((CONTRACTS / "ocd_production_units.yaml").read_text())
RULES = {r["product_kind"]: r["unit_id"] for r in UNITS["rules"]}


def test_pressure_and_temperature_units_cannot_convert():
    with pytest.raises(SemanticError):
        Conversion(Unit("Pa", "pressure"), Unit("degC", "temperature"), 1.0)


def test_same_quantity_conversion_applies():
    psi = Conversion(Unit("psi", "pressure"), Unit("Pa", "pressure"), 6894.757293168)
    assert psi.apply(1.0) == pytest.approx(6894.757, abs=0.001)


@pytest.mark.parametrize(
    "target", [ReferenceType.GAUGE, ReferenceType.ABSOLUTE, ReferenceType.DIFFERENTIAL]
)
def test_unknown_pressure_reference_stays_unknown(target):
    with pytest.raises(SemanticError):
        check_pressure_reference(ReferenceType.UNKNOWN, target)
    check_pressure_reference(ReferenceType.UNKNOWN, ReferenceType.UNKNOWN)


def test_gauge_is_not_absolute():
    with pytest.raises(SemanticError):
        check_pressure_reference(ReferenceType.GAUGE, ReferenceType.ABSOLUTE)


def test_offshore_measurement_cannot_map_to_onshore_class():
    with pytest.raises(SemanticError, match="compatibility assessment"):
        check_tag_mapping(
            "OFFSHORE_SUBSEA_WELL",
            "AETHER_ONSHORE_GAS_WELL",
            ReferenceType.UNKNOWN,
            ReferenceType.UNKNOWN,
        )


@pytest.mark.parametrize("kind", ["Z ", "", None, "MCF"])
def test_ambiguous_product_kind_has_no_default_unit(kind):
    with pytest.raises(AmbiguousUnitError):
        resolve_production_unit(kind, RULES)


def test_padded_product_kinds_resolve_to_verified_units():
    assert resolve_production_unit("G ", RULES) == "MCF_15025PSIA_60F"
    assert resolve_production_unit("O ", RULES) == "BBL_60F"
    assert resolve_production_unit("W ", RULES) == "BBL_60F"


def test_every_unit_rule_cites_the_rule_and_instructions():
    assert {r["verification_status"] for r in UNITS["rules"]} == {"VERIFIED"}
    for rule in UNITS["rules"]:
        cited = {item["ref"] for item in rule["evidence"]}
        assert {"ocd_dictionary", "c115_2025", "c115_2019", "nmac_19_15_2"} <= cited
    for reference in UNITS["references"].values():
        assert len(reference["sha256"]) == 64


def test_effective_date_is_declared_unresolved_not_a_filing_date():
    assert UNITS["dates"]["eff_dte"]["status"] == "UNRESOLVED"
    assert UNITS["dates"]["production_date"]["fields"] == ["prodn_yr", "prodn_mth"]


def asset(**overrides):
    values = {
        "source_asset_id": "x",
        "source_system_id": "nm_ocd",
        "asset_type": "WELL",
        "external_identifier": "x",
        "equipment_class_id": "NM_ONSHORE_WELL",
        "spatial_status": SpatialStatus.NO_LOCATION,
        "batch_id": "b",
        "transformation_id": "t",
        "source_record_key": "k",
    }
    return models.SourceAsset(**{**values, **overrides})


def test_source_asset_contract_rejects_non_observed_and_missing_coordinates():
    with pytest.raises(ValidationError):
        asset(provenance_class=ProvenanceClass.SYNTHETIC)
    with pytest.raises(ValidationError):
        asset(spatial_status=SpatialStatus.USABLE)


def test_contracts_refuse_unknown_fields():
    with pytest.raises(ValidationError):
        asset(unexpected="value")


def event(**overrides):
    values = {
        "event_id": "e",
        "source_system_id": "petrobras_3w",
        "source_instance_id": "i",
        "source_asset_id": "w",
        "source_event_label": 2,
        "source_event_class": "c",
        "start_timestamp": datetime(2020, 1, 1),
        "end_timestamp": datetime(2020, 1, 2),
        "real_or_simulated_source": "REAL",
        "observation_count": 1,
        "parquet_uri": "u",
        "dataset_version": "2.0.0",
        "upstream_checksum": "c",
        "provenance_class": "OBSERVED",
        "batch_id": "b",
        "transformation_id": "t",
    }
    return models.TelemetryEvent(**{**values, **overrides})


def test_telemetry_contract_enforces_origin_rules():
    event()
    with pytest.raises(ValidationError):
        event(source_asset_id=None)
    with pytest.raises(ValidationError):
        event(real_or_simulated_source="SIMULATED", source_asset_id=None)  # Still claims OBSERVED.
    with pytest.raises(ValidationError):
        event(
            real_or_simulated_source="SIMULATED", provenance_class="SYNTHETIC"
        )  # Still has a well.
    event(real_or_simulated_source="SIMULATED", source_asset_id=None, provenance_class="SYNTHETIC")


def test_telemetry_contract_rejects_contradictory_timestamps():
    with pytest.raises(ValidationError):
        event(start_timestamp=datetime(2020, 1, 2), end_timestamp=datetime(2020, 1, 1))


def test_scenario_mapping_contract_refuses_observed():
    with pytest.raises(ValidationError):
        models.ScenarioMapping(
            scenario_id="s",
            target_asset_id="A-01",
            telemetry_event_id="e",
            original_source_instance_id="i",
            transformation_config={},
            compatibility_assessment_id="a",
            mapping_provenance=ProvenanceClass.OBSERVED,
        )


def test_production_contract_requires_first_of_month():
    with pytest.raises(ValidationError):
        models.ProductionRecord(
            source_system_id="nm_ocd",
            reporting_entity_id="e",
            reporting_grain="WELL_COMPLETION",
            reporting_period=date(2026, 6, 30),
            product_kind="G",
            reported_volume=1,
            unit_id="u",
            unit_system="s",
            pool_code="p",
            operator_code="o",
            days_produced=30,
            completion_status_code="F",
            is_amended=False,
            source_effective_at=datetime(2026, 8, 1),
            source_modified_at=None,
            original_record_uri="u",
            batch_id="b",
            transformation_id="t",
            source_record_key="k",
        )


# Spatial rules


def peer(identifier, lat, ulstr="A-01-23S-28E"):
    return {"id": identifier, "ulstr": ulstr, "latitude": lat, "longitude": -104.08}


def test_well_far_from_township_peers_is_an_outlier():
    wells = [peer(str(i), 32.30 + i * 0.001) for i in range(5)] + [peer("bad", 33.30)]
    found = spatial_rules.plss_peer_outliers(wells)
    assert set(found) == {"bad"}
    assert found["bad"]["distance_from_peer_median_km"] > 100


def test_wells_in_a_township_are_not_outliers():
    wells = [peer(str(i), 32.25 + i * 0.02) for i in range(6)]
    assert spatial_rules.plss_peer_outliers(wells) == {}


def test_too_few_peers_produces_no_finding():
    assert spatial_rules.plss_peer_outliers([peer("a", 32.3), peer("b", 33.3)]) == {}


@pytest.mark.parametrize(
    ("arcgis", "ftp", "rule"),
    [
        ("NAD83", "NAD83", None),
        ("NAD27", "NAD83", spatial_rules.DATUM_CONFLICT_RULE),
        ("", "NAD83", spatial_rules.DATUM_MISSING_RULE),
        ("NAD83", None, spatial_rules.DATUM_MISSING_RULE),
        (None, None, spatial_rules.DATUM_MISSING_RULE),
    ],
)
def test_datum_label_findings(arcgis, ftp, rule):
    assert spatial_rules.datum_finding(arcgis, ftp) == rule


def test_outlier_status_outranks_datum_status():
    assert spatial_rules.spatial_status(True, None) is SpatialStatus.QUARANTINED
    assert spatial_rules.spatial_status(False, "rule") is SpatialStatus.UNRESOLVED_DATUM
    assert spatial_rules.spatial_status(False, None) is SpatialStatus.USABLE


# Normalization


def production_row(**overrides):
    row = {
        "api": "30-015-90001", "pool_idn": "97442", "prodn_yr": "2026", "prodn_mth": "6",
        "ogrid_cde": "1", "prd_knd_cde": "G ", "eff_dte": "2026-08-10T19:00:31.220", "amend_ind": "N",
        "c115_wc_stat_cde": "F", "prod_amt": "10", "prodn_day_num": "30", "mod_dte": "2026-08-10T19:02:28.627",
    }  # fmt: skip
    return {**row, **overrides}


def normalize(rows):
    return ocd.normalize_production(rows, RULES, "NM_C115", "WELL_COMPLETION", "raw.zip", "b")


def test_ambiguous_unit_row_is_excluded_and_recorded():
    completions, records, exceptions = normalize([production_row(prd_knd_cde="Z ")])
    assert (completions, records) == ([], [])
    assert exceptions[0].exception_type == "AMBIGUOUS_PRODUCTION_UNIT"
    assert exceptions[0].original_values["prd_knd_cde"] == "Z "


def test_volume_is_not_altered_and_production_month_is_used():
    _, records, _ = normalize([production_row(prod_amt="53612")])
    assert records[0].reported_volume == 53612
    assert records[0].reporting_period == date(2026, 6, 1)
    assert records[0].source_effective_at == datetime(2026, 8, 10, 19, 0, 31, 220000)


def test_two_pools_stay_two_completions():
    completions, records, _ = normalize([production_row(), production_row(pool_idn="98220")])
    assert len(completions) == 2 and len(records) == 2


def test_null_volume_is_not_turned_into_zero():
    _, records, _ = normalize([production_row(prod_amt=None)])
    assert records[0].reported_volume is None


def test_open_ended_history_sentinel_becomes_null():
    row = {
        "api": "30-015-90001", "eff_dte": "2020-01-01T00:00:00", "rec_termn_dte": "9999-12-31T00:00:00",
        "ogrid_cde": "1", "status": "A", "well_typ_cde": "G", "latitude": "3.2e+001", "longitude": "-1.04e+002",
        "datum": "NAD83",
    }  # fmt: skip
    record = ocd.normalize_history([row], "b")[0]
    assert record.valid_to is None
    assert record.attributes["rec_termn_dte"] == "9999-12-31T00:00:00"


def test_3w_event_identity_includes_the_class_label():
    assert petrobras_3w.event_id(2, "SIMULATED_00001") != petrobras_3w.event_id(
        5, "SIMULATED_00001"
    )


@pytest.mark.parametrize(
    ("values", "nulls", "flag"), [(0, 10, "EMPTY"), (5, 5, "PARTIAL"), (10, 0, "COMPLETE")]
)
def test_sensor_quality_flag(values, nulls, flag):
    assert petrobras_3w.quality_flag(values, nulls) == flag


def test_3w_fixture_normalizes_with_origin_rules():
    batch = "petrobras_3w-fixture-2.0.0"
    import json

    manifest = json.loads((CI_WORKSPACE / f"data/manifests/petrobras_3w/{batch}.json").read_text())
    index = pd.read_parquet(CI_WORKSPACE / f"data/bronze/petrobras_3w/{batch}/instances.parquet")
    result = petrobras_3w.normalize_batch(index, CI_WORKSPACE, manifest, COMPATIBILITY["variables"])
    assert len(result.events) == 3
    assert {e.provenance_class for e in result.events} == {
        ProvenanceClass.OBSERVED,
        ProvenanceClass.SYNTHETIC,
    }
    assert len(result.observations) == 3 * 27
    assert len(result.exceptions) == 10


# Compatibility contract


def ini_columns():
    from pipelines.normalize.seed import read_ini

    return set(read_ini()["PARQUET_FILE_PROPERTIES"])


def test_every_3w_variable_is_classified_exactly_once():
    tags = [v["tag"] for v in COMPATIBILITY["variables"]]
    assert len(tags) == len(set(tags))
    assert set(tags) == ini_columns()


def test_every_3w_event_is_classified_exactly_once():
    from pipelines.normalize.seed import read_ini

    names = [n.strip() for n in read_ini()["EVENTS"]["NAMES"].replace("\n", " ").split(",")]
    assert sorted(e["event"] for e in COMPATIBILITY["events"]) == sorted(names)


def test_all_assessments_validate_with_reasoning():
    assessments = build_assessments()
    assert len(assessments) == 30 + 10
    assert all(len(a.reasoning) >= 20 for a in assessments)


def test_subsea_measurements_are_incompatible_with_aether():
    by_tag = {v["tag"]: v["classification"] for v in COMPATIBILITY["variables"]}
    for tag in ("PT-P", "P-TPT", "T-TPT"):
        assert by_tag[tag] == "INCOMPATIBLE"


def test_equipment_aether_lacks_makes_dependent_items_incompatible():
    by_tag = {v["tag"]: v["classification"] for v in COMPATIBILITY["variables"]}
    for tag in (
        "ABER-CKGL",
        "QGL",
        "P-JUS-CKGL",
        "P-MON-CKGL",
        "ESTADO-SDV-GL",
        "ESTADO-DHSV",
        "QBS",
        "P-JUS-BS",
    ):
        assert by_tag[tag] == "INCOMPATIBLE"
    by_event = {e["event"]: e["classification"] for e in COMPATIBILITY["events"]}
    for event_name in ("SPURIOUS_CLOSURE_OF_DHSV", "HYDRATE_IN_SERVICE_LINE"):
        assert by_event[event_name] == "INCOMPATIBLE"


def test_equipment_assessed_as_missing_is_declared_missing_in_the_facility():
    facility = yaml.safe_load((REPO_ROOT / "config/facility/aether_field.yaml").read_text())
    missing = set(facility["equipment_assumptions"]["does_not_have"])
    assert {
        "gas_lift",
        "downhole_safety_valve",
        "service_pump",
        "service_line",
        "subsea_tree",
    } <= missing


def test_nothing_is_directly_compatible():
    items = COMPATIBILITY["variables"] + COMPATIBILITY["events"]
    assert not [i for i in items if i["classification"] == "DIRECTLY_COMPATIBLE"]


def test_only_compatible_classes_are_mappable():
    assert is_mappable(CompatibilityClass.CONDITIONALLY_COMPATIBLE)
    assert not is_mappable(CompatibilityClass.INCOMPATIBLE)
    assert not is_mappable(CompatibilityClass.INSUFFICIENT_EVIDENCE)


def test_all_3w_pressure_tags_seed_as_unknown_on_their_own_class():
    tags, definitions, mappings = build_semantics()
    pressures = [t for t in tags if t.physical_quantity == "pressure"]
    assert len(pressures) == 10
    assert {t.pressure_reference_type for t in pressures} == {ReferenceType.UNKNOWN}
    assert {m.equipment_class_id for m in mappings} == {"OFFSHORE_SUBSEA_WELL"}
    assert {d.equipment_class_id for d in definitions} == {"OFFSHORE_SUBSEA_WELL"}


# Repository metadata and CI


def public_files():
    ignored = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "raw",
        "bronze",
        "fixtures_local",
    }
    for path in REPO_ROOT.rglob("*"):
        if (
            path.is_file()
            and not ignored & set(path.parts)
            and path.suffix not in {".parquet", ".zip", ".lock", ".png"}
        ):
            yield path


def test_no_recruiter_or_company_references_in_project_files():
    pattern = "elec" + "tio"
    this_file = "test_semantics_and_normalize.py"
    for path in public_files():
        if path.name == this_file:
            continue
        for word in path.read_text(errors="ignore").lower().replace(".", " ").split():
            assert word.strip("'\",:;()") != pattern, path


def test_ci_uses_no_live_endpoints_or_aws():
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text()
    assert "-m live" not in workflow
    assert "make acquire" not in workflow
    assert "aws " not in workflow.lower()
    assert "AWS_" not in workflow
    assert "permissions:" in workflow


def test_ci_actions_are_pinned_to_commits():
    import re

    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text()
    uses = re.findall(r"uses:\s*(\S+)", workflow)
    assert uses
    assert all(re.search(r"@[0-9a-f]{40}$", action) for action in uses), uses
