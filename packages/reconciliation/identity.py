"""Identity reconciliation. Only a shared authoritative identifier can establish identity."""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.domain.models import ProvenanceClass
from packages.domain.reconciliation import (
    EntityType,
    Method,
    Module,
    ReconciliationDecision,
    Relationship,
    Status,
)


class IdentityBoundaryError(ValueError):
    """An attempt to treat a real source entity and a fictional asset as one identity."""


class UnverifiedIdentityError(ValueError):
    """A mapping relied on an identity that isn't verified."""


@dataclass(frozen=True)
class RecordRef:
    entity_type: EntityType
    record_id: str
    source_system: str
    identifiers: dict[str, str] = field(default_factory=dict)
    name: str | None = None


def match_identity(
    a: RecordRef,
    b: RecordRef,
    authoritative_types: set[str],
    algorithm: str,
    batch_id: str | None = None,
) -> ReconciliationDecision:
    """Compare two records. Names and locations are recorded as not considered, and never decide."""
    if EntityType.ASSET in (a.entity_type, b.entity_type):
        raise IdentityBoundaryError(
            f"{a.record_id} and {b.record_id}: a fictional asset has no real-world identity"
        )
    shared = sorted(authoritative_types & set(a.identifiers) & set(b.identifiers))
    evidence: dict[str, object] = {
        "identifier_types_compared": shared,
        "name_or_location_used": False,
    }
    if a.name and b.name and a.name.strip().lower() == b.name.strip().lower():
        evidence["names_match_but_are_not_evidence_of_identity"] = True

    if not shared:
        status, method = Status.UNRESOLVED, Method.NO_SHARED_IDENTIFIER
        evidence["reason"] = "No authoritative identifier type is present on both records."
    elif all(a.identifiers[t].strip() == b.identifiers[t].strip() for t in shared):
        status, method = Status.VERIFIED, Method.AUTHORITATIVE_IDENTIFIER
        evidence["identifiers"] = {t: a.identifiers[t] for t in shared}
    else:
        status, method = Status.REJECTED, Method.AUTHORITATIVE_IDENTIFIER
        evidence["identifiers_a"] = {t: a.identifiers[t] for t in shared}
        evidence["identifiers_b"] = {t: b.identifiers[t] for t in shared}

    return ReconciliationDecision(
        module=Module.IDENTITY,
        subject_type=a.entity_type,
        subject_id=a.record_id,
        object_type=b.entity_type,
        object_id=b.record_id,
        relationship_type=Relationship.SAME_AS,
        method=method,
        evidence=evidence,
        verification_status=status,
        provenance_class=ProvenanceClass.DERIVED,
        algorithm_version=algorithm,
        batch_id=batch_id,
    )


def require_verified_identity(decision: ReconciliationDecision | None) -> None:
    """Refuse to build on an identity that isn't verified, including a missing decision."""
    if decision is None or decision.relationship_type is not Relationship.SAME_AS:
        raise UnverifiedIdentityError("no identity decision exists for this mapping")
    if decision.verification_status is not Status.VERIFIED:
        raise UnverifiedIdentityError(
            f"identity of {decision.subject_id} is {decision.verification_status}"
        )
