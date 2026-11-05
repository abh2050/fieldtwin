"""Measurement rules shared by loaders and tests. Invalid conversions raise rather than guess."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CompatibilityClass, ReferenceType


class SemanticError(ValueError):
    """A measurement relationship or conversion that is not physically supported."""


class AmbiguousUnitError(SemanticError):
    """A source value whose unit cannot be established."""


@dataclass(frozen=True)
class Unit:
    unit_id: str
    physical_quantity: str


@dataclass(frozen=True)
class Conversion:
    from_unit: Unit
    to_unit: Unit
    factor: float
    term: float = 0.0

    def __post_init__(self) -> None:
        if self.from_unit.physical_quantity != self.to_unit.physical_quantity:
            raise SemanticError(
                f"cannot convert {self.from_unit.unit_id} ({self.from_unit.physical_quantity}) to "
                f"{self.to_unit.unit_id} ({self.to_unit.physical_quantity})"
            )

    def apply(self, value: float) -> float:
        return value * self.factor + self.term


def check_pressure_reference(source: ReferenceType, target: ReferenceType) -> None:
    """A unit conversion can't change the reference frame, and unknown stays unknown."""
    if source is ReferenceType.UNKNOWN and target is not ReferenceType.UNKNOWN:
        raise SemanticError(f"unknown pressure reference cannot be treated as {target}")
    if source is not target:
        raise SemanticError(f"{source} pressure is not {target} pressure")


def convert_pressure(
    value,
    source: ReferenceType,
    target: ReferenceType,
    ambient_pa_abs: float | None = None,
):
    """Change the pressure reference frame, in pascals. This needs ambient pressure, stated."""
    if source is target and source is not ReferenceType.UNKNOWN:
        return value
    allowed = {ReferenceType.ABSOLUTE, ReferenceType.GAUGE}
    if source not in allowed or target not in allowed:
        raise SemanticError(f"{source} pressure cannot be converted to {target} pressure")
    if ambient_pa_abs is None or ambient_pa_abs <= 0:
        raise SemanticError("converting between absolute and gauge needs a stated ambient pressure")
    if source is ReferenceType.ABSOLUTE:
        return value - ambient_pa_abs
    return value + ambient_pa_abs


def check_unit_defined(unit_id: str | None, known_units: set[str]) -> None:
    if not unit_id or unit_id not in known_units:
        raise SemanticError(f"unit {unit_id!r} has no definition")


def check_tag_mapping(
    tag_equipment_class: str,
    definition_equipment_class: str,
    tag_reference: ReferenceType,
    definition_reference: ReferenceType,
) -> None:
    """Python counterpart of the sensor_tag_mappings foreign keys, for a clearer error."""
    if tag_equipment_class != definition_equipment_class:
        raise SemanticError(
            f"{tag_equipment_class} measurement cannot map to {definition_equipment_class}. "
            "Crossing domains needs a compatibility assessment and a scenario mapping."
        )
    check_pressure_reference(tag_reference, definition_reference)


def resolve_production_unit(product_kind: str | None, rules: dict[str, str]) -> str:
    """Return the verified unit for a product kind. There is no default."""
    kind = (product_kind or "").strip()
    if kind not in rules:
        raise AmbiguousUnitError(f"no verified unit for product kind {product_kind!r}")
    return rules[kind]


def is_mappable(classification: CompatibilityClass) -> bool:
    return classification in (
        CompatibilityClass.DIRECTLY_COMPATIBLE,
        CompatibilityClass.CONDITIONALLY_COMPATIBLE,
    )
