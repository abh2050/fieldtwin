"""Audit of 3W observation labels. Source labels are read and classified, and never changed."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

TRANSIENT_OFFSET = 100
NULL_LABEL = -1


class Evaluability(StrEnum):
    FULLY_LABELED = "FULLY_LABELED"
    PARTIALLY_LABELED = "PARTIALLY_LABELED"
    AMBIGUOUS_OR_INCONSISTENT = "AMBIGUOUS_OR_INCONSISTENT"


@dataclass(frozen=True)
class InstanceAudit:
    source_instance_id: str
    source_well_id: str | None
    origin: str
    filed_class: int
    event_class_name: str
    rows: int
    null_rows: int
    normal_rows: int
    steady_event_rows: int
    transient_event_rows: int
    other_class_rows: int
    null_is_leading_only: bool
    evaluability: str
    reason: str
    eligible_event_positive: bool
    eligible_sample_level: bool
    eligible_normal_exposure: bool
    has_pre_event_normal: bool

    def to_dict(self) -> dict:
        return asdict(self)


def audit_labels(
    labels: np.ndarray,
    *,
    instance_id: str,
    well_id: str | None,
    origin: str,
    filed_class: int,
    class_name: str,
) -> InstanceAudit:
    """Classify one instance. `labels` holds source values, with NaN where the source has no label."""
    labels = np.asarray(labels, dtype=float)
    null = np.isnan(labels)
    known = labels[~null].astype(int)
    steady = int(np.sum((known == filed_class) & (filed_class != 0)))
    transient = int(np.sum(known == filed_class + TRANSIENT_OFFSET)) if filed_class else 0
    normal = int(np.sum(known == 0))
    other = int(known.size - normal - steady - transient)
    first_known = int(np.argmax(~null)) if (~null).any() else len(labels)
    leading_only = not null[first_known:].any()
    has_event = steady + transient > 0

    if other > 0:
        grade, reason = (
            Evaluability.AMBIGUOUS_OR_INCONSISTENT,
            "Contains labels of a class other than the one it is filed under.",
        )
    elif filed_class != 0 and not has_event:
        grade, reason = (
            Evaluability.AMBIGUOUS_OR_INCONSISTENT,
            "Filed under an event class, with no event-labeled row.",
        )
    elif null.any():
        grade, reason = Evaluability.PARTIALLY_LABELED, "Some rows have no source label."
    else:
        grade, reason = Evaluability.FULLY_LABELED, "Every row has a consistent label."

    usable = grade is not Evaluability.AMBIGUOUS_OR_INCONSISTENT
    first_event = _first_event_index(known, filed_class)
    return InstanceAudit(
        source_instance_id=instance_id,
        source_well_id=well_id,
        origin=origin,
        filed_class=filed_class,
        event_class_name=class_name,
        rows=len(labels),
        null_rows=int(null.sum()),
        normal_rows=normal,
        steady_event_rows=steady,
        transient_event_rows=transient,
        other_class_rows=other,
        null_is_leading_only=bool(leading_only),
        evaluability=grade.value,
        reason=reason,
        eligible_event_positive=usable and filed_class != 0 and has_event,
        eligible_sample_level=usable,
        # Ambiguous instances are held out of both sides. They aren't treated as normal.
        eligible_normal_exposure=usable and normal > 0,
        has_pre_event_normal=first_event is not None and first_event > 0,
    )


def _first_event_index(known: np.ndarray, filed_class: int) -> int | None:
    if filed_class == 0:
        return None
    hits = np.flatnonzero(known != 0)
    return int(hits[0]) if hits.size else None


def summarize(audits: pd.DataFrame) -> pd.DataFrame:
    """Counts by origin, class, and grade."""
    return (
        audits.groupby(["origin", "filed_class", "event_class_name", "evaluability"])
        .agg(
            instances=("source_instance_id", "size"),
            wells=("source_well_id", "nunique"),
            hours=("rows", lambda rows: rows.sum() / 3600.0),
            event_eligible=("eligible_event_positive", "sum"),
            with_pre_event_normal=("has_pre_event_normal", "sum"),
        )
        .reset_index()
    )
