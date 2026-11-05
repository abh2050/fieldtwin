"""Semantic measurement reconciliation. Tags keep their native equipment semantics."""

from __future__ import annotations

from dataclasses import dataclass

from packages.domain.models import CompatibilityClass, ProvenanceClass, ReferenceType
from packages.domain.reconciliation import (
    EntityType,
    Method,
    Module,
    ReconciliationDecision,
    Relationship,
    Status,
)
from packages.domain.semantics import (
    SemanticError,
    check_pressure_reference,
    check_tag_mapping,
    check_unit_defined,
    is_mappable,
)


class CompatibilityError(SemanticError):
    """A mapping that the compatibility assessment doesn't allow."""


@dataclass(frozen=True)
class TagView:
    tag_id: str
    source_system_id: str
    equipment_class_id: str
    physical_quantity: str
    unit_id: str | None
    reference: ReferenceType


@dataclass(frozen=True)
class DefinitionView:
    definition_id: str
    equipment_class_id: str
    physical_quantity: str
    unit_id: str | None
    reference: ReferenceType


def validate_measurement_mapping(tag: TagView, definition: DefinitionView, units: set[str]) -> None:
    """Raise if a tag can't map to a definition. Similar units or names are never enough."""
    check_unit_defined(tag.unit_id, units)
    check_unit_defined(definition.unit_id, units)
    if tag.physical_quantity != definition.physical_quantity:
        raise SemanticError(
            f"{tag.tag_id} measures {tag.physical_quantity}, not {definition.physical_quantity}"
        )
    check_tag_mapping(
        tag.equipment_class_id,
        definition.equipment_class_id,
        tag.reference,
        definition.reference,
    )


def require_compatible(subject: str, classification: CompatibilityClass | None) -> None:
    """A missing assessment is refused, the same as a negative one."""
    if classification is None:
        raise CompatibilityError(f"{subject} has no compatibility assessment")
    if not is_mappable(classification):
        raise CompatibilityError(f"{subject} is {classification}")


def native_decision(
    tag: TagView,
    definition: DefinitionView,
    units: set[str],
    algorithm: str,
    method: Method = Method.PUBLISHED_DEFINITION_SAME_CLASS,
    provenance: ProvenanceClass = ProvenanceClass.DERIVED,
) -> ReconciliationDecision:
    """Record a tag against the definition of its own class. An unknown reference stays unresolved."""
    validate_measurement_mapping(tag, definition, units)
    unknown = tag.reference is ReferenceType.UNKNOWN
    evidence: dict[str, object] = {
        "equipment_class": tag.equipment_class_id,
        "unit": tag.unit_id,
        "reference": tag.reference.value,
    }
    if unknown:
        evidence["unresolved_because"] = "The source doesn't state the pressure reference type."
    return ReconciliationDecision(
        module=Module.SEMANTIC,
        subject_type=EntityType.SENSOR_TAG,
        subject_id=tag.tag_id,
        object_type=EntityType.MEASUREMENT_DEFINITION,
        object_id=definition.definition_id,
        relationship_type=Relationship.SAME_MEASUREMENT,
        method=method,
        evidence=evidence,
        verification_status=Status.UNRESOLVED if unknown else Status.VERIFIED,
        provenance_class=provenance,
        algorithm_version=algorithm,
    )


def rejected_cross_domain_decision(
    tag: TagView, definition: DefinitionView, units: set[str], algorithm: str
) -> ReconciliationDecision:
    """Attempt a mapping that must fail, and record why. Succeeding here is a programming error."""
    try:
        validate_measurement_mapping(tag, definition, units)
    except SemanticError as error:
        reason = str(error)
    else:
        raise CompatibilityError(
            f"{tag.tag_id} to {definition.definition_id} was expected to be refused"
        )
    return ReconciliationDecision(
        module=Module.SEMANTIC,
        subject_type=EntityType.SENSOR_TAG,
        subject_id=tag.tag_id,
        object_type=EntityType.MEASUREMENT_DEFINITION,
        object_id=definition.definition_id,
        relationship_type=Relationship.SAME_MEASUREMENT,
        method=Method.COMPATIBILITY_VALIDATION,
        evidence={"refused_because": reason},
        verification_status=Status.REJECTED,
        provenance_class=ProvenanceClass.DERIVED,
        algorithm_version=algorithm,
    )


__all__ = [
    "CompatibilityError",
    "DefinitionView",
    "TagView",
    "check_pressure_reference",
    "native_decision",
    "rejected_cross_domain_decision",
    "require_compatible",
    "validate_measurement_mapping",
]
