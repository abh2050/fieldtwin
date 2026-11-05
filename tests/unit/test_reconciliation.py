"""Negative tests for the reconciliation engine, with no database."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.domain.events import EventDomain, EventKind, PrioritizationInput, SharedEvent
from packages.domain.models import (
    CompatibilityClass,
    InstanceOrigin,
    ProvenanceClass,
    ReferenceType,
    SpatialStatus,
)
from packages.domain.reconciliation import (
    EntityType,
    Method,
    Module,
    ReconciliationDecision,
    Relationship,
    Status,
)
from packages.domain.semantics import SemanticError
from packages.reconciliation.geospatial import Located, candidates_near
from packages.reconciliation.identity import (
    IdentityBoundaryError,
    RecordRef,
    UnverifiedIdentityError,
    match_identity,
    require_verified_identity,
)
from packages.reconciliation.provenance import (
    ProvenanceError,
    expected_instance_provenance,
    require_provenance,
    require_simulated_is_synthetic,
)
from packages.reconciliation.scenario import (
    DomainBoundaryError,
    EquipmentRelationshipError,
    assignment_decision,
    require_scenario_source,
    validate_equipment_relationship,
)
from packages.reconciliation.semantic import (
    CompatibilityError,
    DefinitionView,
    TagView,
    native_decision,
    rejected_cross_domain_decision,
    require_compatible,
    validate_measurement_mapping,
)
from pipelines.normalize.petrobras_3w_events import to_shared_event

ALGORITHM = "test@1"
API = {"API_NUMBER"}
UNITS = {"Pa", "degC", "sm3_per_s"}


def well(
    record_id="nm_ocd:well:30-015-90001",
    api="30-015-90001",
    name=None,
    kind=EntityType.SOURCE_ASSET,
):
    identifiers = {"API_NUMBER": api} if api else {}
    return RecordRef(kind, record_id, "nm_ocd", identifiers, name)


def decision(**overrides):
    values = {
        "module": Module.IDENTITY,
        "subject_type": EntityType.SOURCE_ASSET,
        "subject_id": "a",
        "object_type": EntityType.SOURCE_RECORD,
        "object_id": "b",
        "relationship_type": Relationship.SAME_AS,
        "method": Method.AUTHORITATIVE_IDENTIFIER,
        "evidence": {"reason": "test"},
        "verification_status": Status.VERIFIED,
        "provenance_class": ProvenanceClass.DERIVED,
        "algorithm_version": ALGORITHM,
    }
    return ReconciliationDecision(**{**values, **overrides})


# Identity


def test_shared_authoritative_identifier_verifies_identity():
    result = match_identity(well(), well("ftp:1", kind=EntityType.SOURCE_RECORD), API, ALGORITHM)
    assert result.verification_status is Status.VERIFIED
    assert result.method is Method.AUTHORITATIVE_IDENTIFIER
    assert result.evidence["name_or_location_used"] is False
    assert result.algorithm_version == ALGORITHM


def test_identical_names_without_an_identifier_stay_unresolved():
    a = well(api=None, name="SMITH FEDERAL #1")
    b = well("other", api=None, name="SMITH FEDERAL #1", kind=EntityType.SOURCE_RECORD)
    result = match_identity(a, b, API, ALGORITHM)
    assert result.verification_status is Status.UNRESOLVED
    assert result.evidence["names_match_but_are_not_evidence_of_identity"] is True


def test_identical_names_with_different_identifiers_are_rejected():
    a = well(name="SMITH FEDERAL #1")
    b = well("other", "30-015-90002", "SMITH FEDERAL #1", EntityType.SOURCE_RECORD)
    assert match_identity(a, b, API, ALGORITHM).verification_status is Status.REJECTED


def test_non_authoritative_identifier_type_cannot_verify():
    a = RecordRef(EntityType.SOURCE_ASSET, "a", "nm_ocd", {"LOCAL_NAME": "X"})
    b = RecordRef(EntityType.SOURCE_RECORD, "b", "nm_ocd", {"LOCAL_NAME": "X"})
    assert match_identity(a, b, API, ALGORITHM).verification_status is Status.UNRESOLVED


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_real_source_asset_cannot_become_a_fictional_asset(order):
    pair = [well(), well("A-03", "30-015-90001", kind=EntityType.ASSET)]
    with pytest.raises(IdentityBoundaryError):
        match_identity(pair[order[0]], pair[order[1]], API, ALGORITHM)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        decision(verification_status=Status.UNRESOLVED, method=Method.NO_SHARED_IDENTIFIER),
        decision(verification_status=Status.REJECTED),
        decision(verification_status=Status.UNVERIFIED),
        decision(relationship_type=Relationship.COMPLETION_OF),
    ],
)
def test_unverified_identity_cannot_be_built_on(bad):
    with pytest.raises(UnverifiedIdentityError):
        require_verified_identity(bad)


# Decision contract


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject_type": EntityType.SOURCE_ASSET, "object_type": EntityType.ASSET},
        {"subject_type": EntityType.ASSET, "object_type": EntityType.SOURCE_ASSET},
        {"subject_type": EntityType.ASSET, "object_type": EntityType.SOURCE_RECORD},
        {"method": Method.NAME_SIMILARITY},
        {"method": Method.GEOSPATIAL_PROXIMITY},
        {"method": Method.UNIT_SIMILARITY},
        {"method": Method.HUMAN_REVIEW},
        {"provenance_class": ProvenanceClass.INFERRED},
        {"evidence": {}},
        {"algorithm_version": "unversioned"},
        {"confidence": 1.5},
        {"object_id": None},
        {"relationship_type": Relationship.PROXIMITY_CANDIDATE},
        {"relationship_type": Relationship.EXPERIMENTAL_ASSIGNMENT},
    ],
)
def test_invalid_decisions_are_refused(overrides):
    with pytest.raises(ValidationError):
        decision(**overrides)


def test_verified_and_inferred_are_always_distinguishable():
    verified = decision()
    inferred = decision(
        relationship_type=Relationship.PROXIMITY_CANDIDATE,
        method=Method.GEOSPATIAL_PROXIMITY,
        verification_status=Status.UNVERIFIED,
        provenance_class=ProvenanceClass.INFERRED,
    )
    assert (verified.verification_status, verified.provenance_class) != (
        inferred.verification_status,
        inferred.provenance_class,
    )


def test_decision_carries_every_required_element():
    fields = set(ReconciliationDecision.model_fields)
    required = {
        "subject_id", "object_id", "relationship_type", "method", "evidence", "confidence",
        "uncertainty", "verification_status", "algorithm_version",
    }  # fmt: skip
    assert required <= fields


# Geospatial


def located(record, lat=32.3, lon=-104.1, status=SpatialStatus.USABLE):
    return Located(EntityType.SOURCE_ASSET, record, lat, lon, status)


def test_identical_coordinates_produce_only_a_candidate():
    found = candidates_near(located("a"), [located("b")], 100.0, ALGORITHM)
    assert len(found) == 1
    result = found[0]
    assert result.relationship_type is Relationship.PROXIMITY_CANDIDATE
    assert result.verification_status is Status.UNVERIFIED
    assert result.provenance_class is ProvenanceClass.INFERRED
    assert result.confidence is None
    assert result.evidence["distance_m"] == 0.0


def test_proximity_cannot_be_stored_as_identity():
    with pytest.raises(ValidationError):
        decision(
            relationship_type=Relationship.SAME_AS,
            method=Method.GEOSPATIAL_PROXIMITY,
            verification_status=Status.UNVERIFIED,
            provenance_class=ProvenanceClass.INFERRED,
        )


def test_distance_outside_the_radius_is_excluded():
    assert candidates_near(located("a"), [located("b", lat=32.31)], 100.0, ALGORITHM) == []


@pytest.mark.parametrize("status", [SpatialStatus.QUARANTINED, SpatialStatus.UNRESOLVED_DATUM])
def test_excluded_coordinates_take_no_part(status):
    assert candidates_near(located("a"), [located("b", status=status)], 100.0, ALGORITHM) == []
    assert candidates_near(located("a", status=status), [located("b")], 100.0, ALGORITHM) == []


def test_a_record_is_not_its_own_candidate():
    assert candidates_near(located("a"), [located("a")], 100.0, ALGORITHM) == []


def test_emission_near_remains_a_candidate_and_widens_with_footprint():
    plume = Located(EntityType.OBSERVATION, "plume", 32.3, -104.1)
    asset = located("well", lat=32.3012)  # About 133 m away.
    assert candidates_near(plume, [asset], 100.0, ALGORITHM, Relationship.EMISSION_NEAR) == []
    found = candidates_near(
        plume, [asset], 100.0, ALGORITHM, Relationship.EMISSION_NEAR, footprint_uncertainty_m=50.0
    )
    assert found[0].relationship_type is Relationship.EMISSION_NEAR
    assert found[0].uncertainty["footprint_uncertainty_m"] == 50.0
    assert found[0].verification_status is Status.UNVERIFIED


# Semantics and compatibility


def offshore(native="PT-P", quantity="pressure", unit="Pa", reference=ReferenceType.UNKNOWN):
    return TagView(
        f"petrobras_3w:{native}", "petrobras_3w", "OFFSHORE_SUBSEA_WELL", quantity, unit, reference
    )


def onshore(quantity="pressure", unit="Pa", reference=ReferenceType.GAUGE):
    return DefinitionView(
        "aether_well.tubing_head_pressure", "AETHER_ONSHORE_GAS_WELL", quantity, unit, reference
    )


def test_offshore_sensor_cannot_map_to_onshore_equipment():
    with pytest.raises(SemanticError, match="cannot map"):
        validate_measurement_mapping(offshore(reference=ReferenceType.GAUGE), onshore(), UNITS)


def test_matching_units_do_not_make_measurements_the_same():
    """Both are pascals and both claim gauge, and the mapping is still refused."""
    with pytest.raises(SemanticError):
        validate_measurement_mapping(offshore(reference=ReferenceType.GAUGE), onshore(), UNITS)


def test_unknown_reference_cannot_become_gauge_within_a_class():
    definition = DefinitionView("d", "OFFSHORE_SUBSEA_WELL", "pressure", "Pa", ReferenceType.GAUGE)
    with pytest.raises(SemanticError, match="unknown"):
        validate_measurement_mapping(offshore(), definition, UNITS)


def test_gauge_tag_cannot_map_to_absolute_definition():
    tag = TagView(
        "t", "aether_synthetic", "AETHER_GATHERING", "pressure", "Pa", ReferenceType.GAUGE
    )
    definition = DefinitionView("d", "AETHER_GATHERING", "pressure", "Pa", ReferenceType.ABSOLUTE)
    with pytest.raises(SemanticError):
        validate_measurement_mapping(tag, definition, UNITS)


@pytest.mark.parametrize("unit", [None, "", "furlongs"])
def test_missing_unit_definition_is_refused(unit):
    with pytest.raises(SemanticError, match="no definition"):
        validate_measurement_mapping(offshore(unit=unit), onshore(), UNITS)


def test_different_quantities_are_refused():
    tag = offshore("T-TPT", "temperature", "degC", ReferenceType.NOT_APPLICABLE)
    with pytest.raises(SemanticError, match="measures"):
        validate_measurement_mapping(tag, onshore(), UNITS)


def test_native_mapping_keeps_unknown_pressure_unresolved():
    definition = DefinitionView(
        "offshore.pt", "OFFSHORE_SUBSEA_WELL", "pressure", "Pa", ReferenceType.UNKNOWN
    )
    result = native_decision(offshore(), definition, UNITS, ALGORITHM)
    assert result.verification_status is Status.UNRESOLVED
    assert "unresolved_because" in result.evidence


def test_cross_domain_attempt_is_recorded_as_rejected():
    result = rejected_cross_domain_decision(offshore(), onshore(), UNITS, ALGORITHM)
    assert result.verification_status is Status.REJECTED
    assert "refused_because" in result.evidence


def test_expecting_a_refusal_that_does_not_happen_is_an_error():
    tag = TagView("t", "x", "C", "pressure", "Pa", ReferenceType.GAUGE)
    definition = DefinitionView("d", "C", "pressure", "Pa", ReferenceType.GAUGE)
    with pytest.raises(CompatibilityError):
        rejected_cross_domain_decision(tag, definition, UNITS, ALGORITHM)


@pytest.mark.parametrize(
    "classification",
    [None, CompatibilityClass.INCOMPATIBLE, CompatibilityClass.INSUFFICIENT_EVIDENCE],
)
def test_missing_or_negative_assessment_is_refused(classification):
    with pytest.raises(CompatibilityError):
        require_compatible("x", classification)


# Provenance


@pytest.mark.parametrize("value", [None, "", "MEASURED"])
def test_missing_or_unknown_provenance_is_refused(value):
    with pytest.raises(ProvenanceError):
        require_provenance(value)


@pytest.mark.parametrize("value", ["OBSERVED", "DERIVED", "REPLAYED", "INFERRED", None])
def test_simulated_observation_must_be_synthetic(value):
    with pytest.raises(ProvenanceError):
        require_simulated_is_synthetic(value)
    require_simulated_is_synthetic("SYNTHETIC")


def test_generated_3w_instances_are_expected_to_be_synthetic():
    assert expected_instance_provenance(InstanceOrigin.REAL) is ProvenanceClass.OBSERVED
    assert expected_instance_provenance(InstanceOrigin.SIMULATED) is ProvenanceClass.SYNTHETIC
    assert expected_instance_provenance(InstanceOrigin.HAND_DRAWN) is ProvenanceClass.SYNTHETIC


# Scenario boundary


@pytest.mark.parametrize("source", ["petrobras_3w", "nm_ocd"])
def test_real_sources_cannot_be_mapped_onto_aether(source):
    with pytest.raises(DomainBoundaryError):
        require_scenario_source(source, "FICTIONAL_ONSHORE")
    require_scenario_source("aether_synthetic", "FICTIONAL_ONSHORE")


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("COMPRESSOR", "WELL"),
        ("WELL", "COMPRESSOR"),
        ("GATHERING_SEGMENT", "WELL"),
        ("WELL", "WELL"),
    ],
)
def test_invalid_equipment_relationships_are_refused(source, target):
    with pytest.raises(EquipmentRelationshipError):
        validate_equipment_relationship(source, "FEEDS", target)


def test_assignment_is_declared_and_never_verified():
    result = assignment_decision("run", "A-03", "a" * 64, 1, ALGORITHM)
    assert result.verification_status is Status.UNVERIFIED
    assert result.provenance_class is ProvenanceClass.SYNTHETIC
    assert result.method is Method.DECLARED_BY_SCENARIO_CONFIG


# Shared events


def benchmark(**overrides):
    values = {
        "event_id": "e",
        "domain": EventDomain.OFFSHORE_BENCHMARK,
        "event_kind": EventKind.SOURCE_LABEL,
        "event_class": "SEVERE_SLUGGING",
        "source_system_id": "petrobras_3w",
        "telemetry_event_id": "t",
        "evidence": {"source_instance_id": "WELL-1"},
        "provenance_class": ProvenanceClass.DERIVED,
        "transformation_id": "x@1",
    }
    return SharedEvent(**{**values, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_asset_id": "A-03"},
        {"affected_asset_id": "GS-A"},
        {"scenario_id": "AETHER-FAULT-001"},
        {"scenario_run_id": "run"},
        {"telemetry_event_id": None},
        {"event_kind": EventKind.INTEGRATION_PROOF_RULE},
        {"source_system_id": "aether_synthetic"},
        {"provenance_class": ProvenanceClass.OBSERVED},
    ],
)
def test_benchmark_event_cannot_reach_aether(overrides):
    with pytest.raises(ValidationError):
        benchmark(**overrides)


def aether_event(**overrides):
    values = {
        "event_id": "e",
        "domain": EventDomain.AETHER_SYNTHETIC,
        "event_kind": EventKind.KNOWN_SYNTHETIC_ONSET,
        "event_class": "PROGRESSIVE_GATHERING_LINE_RESTRICTION",
        "source_system_id": "aether_synthetic",
        "scenario_id": "S",
        "scenario_run_id": "R",
        "target_asset_id": "A-03",
        "affected_asset_id": "GS-A",
        "evidence": {"basis": "declared"},
        "provenance_class": ProvenanceClass.SYNTHETIC,
        "transformation_id": "x@1",
    }
    return SharedEvent(**{**values, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"provenance_class": ProvenanceClass.OBSERVED},
        {"source_system_id": "petrobras_3w"},
        {"telemetry_event_id": "3w-instance"},
        {"event_kind": EventKind.SOURCE_LABEL},
        {"scenario_id": None},
        {"target_asset_id": None},
        {"evidence": {}},
    ],
)
def test_aether_event_must_stay_synthetic_and_scoped(overrides):
    with pytest.raises(ValidationError):
        aether_event(**overrides)


def test_prioritization_input_has_no_score_or_recommendation():
    payload = PrioritizationInput.from_event(
        aether_event(), "Synthetic telemetry from a fictional well."
    )
    assert payload.priority_score is None and payload.recommended_action is None
    with pytest.raises(ValidationError):
        PrioritizationInput(**{**payload.model_dump(), "priority_score": 0.9})


def test_benchmark_event_cannot_enter_aether_prioritization():
    with pytest.raises(ValueError, match="only AETHER"):
        PrioritizationInput.from_event(benchmark(), "Synthetic telemetry from a fictional well.")


def test_adapter_keeps_source_identity_and_origin():
    real = to_shared_event(
        "3w:2:WELL-1", "WELL-1", 2, "SPURIOUS_CLOSURE_OF_DHSV", "REAL", "well-1", "u", 10
    )
    assert real.provenance_class is ProvenanceClass.DERIVED
    assert real.evidence["source_instance_id"] == "WELL-1"
    assert real.evidence["source_event_label"] == 2
    assert real.target_asset_id is None
    for origin in ("SIMULATED", "HAND_DRAWN"):
        generated = to_shared_event("3w:2:S", "S", 2, "C", origin, None, "u", 10)
        assert generated.provenance_class is ProvenanceClass.SYNTHETIC
        assert generated.evidence["real_or_simulated_source"] == origin
