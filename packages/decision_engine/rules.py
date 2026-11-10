"""The transparent rule engine: one detector alarm in, one explained recommendation out.

Every point in the priority score comes from a named term with its input and rule, so a reader can
recompute it by hand. Detector scores only gate "an alarm started"; they are never treated as failure
probabilities, because Gate 5 calibrated thresholds for alarm budgets, not probabilities.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .topology import FieldTopology


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Action(StrEnum):
    FIELD_INSPECTION = "FIELD_INSPECTION"
    CHECK_INSTRUMENTATION = "CHECK_INSTRUMENTATION"
    NO_ACTION_PLANNED_OPERATION = "NO_ACTION_PLANNED_OPERATION"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"


class EvidenceSensor(_Strict):
    tag: str
    asset_id: str
    deviation: float | None
    degraded_quality: bool


class Alarm(_Strict):
    """A detector alarm start. INFERRED from SYNTHETIC telemetry; it carries no fault truth."""

    alarm_id: str
    scenario_id: str
    scenario_run_id: str
    started_at: datetime
    score: float
    threshold: float
    model_id: str
    model_version: str
    model_sha256: str
    evidence: list[EvidenceSensor]
    earlier_starts_in_lookback: int = Field(ge=0)
    first_alarm_at: datetime
    provenance_class: Literal["INFERRED"] = "INFERRED"
    input_provenance: Literal["SYNTHETIC"] = "SYNTHETIC"


class PlannedOperation(_Strict):
    kind: str
    asset_id: str
    start: datetime
    end: datetime


class Context(_Strict):
    """What an operator would know at decision time. Simulator truth is not part of it."""

    planned_operations: list[PlannedOperation] = []
    open_inspection_request_assets: list[str] = []


class ScoreTerm(_Strict):
    name: str
    points: int
    input: str
    rule: str


class Recommendation(_Strict):
    recommendation_id: str
    alarm_id: str
    scenario_id: str
    scenario_run_id: str
    decided_at: datetime
    action: Action
    candidate_assets: list[str]
    suppressed_assets: list[str]
    priority_score: int
    priority_band: str | None
    respond_within_h: int | None
    terms: list[ScoreTerm]
    explanation: list[str]
    rules_version: int
    model_id: str
    model_version: str
    model_sha256: str
    provenance_class: Literal["SYNTHETIC"] = "SYNTHETIC"
    failure_probability: None = None


def _covered(
    asset: str, at: datetime, context: Context, topology: FieldTopology, upstream: bool
) -> PlannedOperation | None:
    for op in context.planned_operations:
        if not (op.start <= at < op.end):
            continue
        covered = topology.assets_through(op.asset_id) if upstream else {op.asset_id}
        if asset in covered:
            return op
    return None


def _band(score: int, bands: Sequence[dict[str, Any]]) -> tuple[str, int | None]:
    for band in sorted(bands, key=lambda b: -b["floor"]):
        if score >= band["floor"]:
            return band["band"], band["respond_within_h"]
    raise ValueError("priority bands must include a zero floor")


def evaluate(
    alarm: Alarm, context: Context, topology: FieldTopology, rules: dict[str, Any]
) -> Recommendation:
    """Apply the declared rules in a fixed order. The same inputs always give the same output."""
    at = alarm.started_at
    explanation: list[str] = [
        f"Detector {alarm.model_id} v{alarm.model_version} started an alarm at {at:%Y-%m-%d %H:%M} "
        f"(score {alarm.score:.3f} over threshold {alarm.threshold:.3f}). The score gates the alarm "
        "only; it is not a failure probability."
    ]
    ordered: list[str] = []
    for sensor in alarm.evidence:
        if sensor.asset_id not in ordered:
            ordered.append(sensor.asset_id)
    if ordered:
        explanation.append(
            "Sensors furthest from training normal: "
            + ", ".join(sensor.tag for sensor in alarm.evidence)
            + f". Their assets are the candidates: {', '.join(ordered)}. This points to data, not a cause."
        )

    context_rules = rules["operating_context"]
    suppressed, candidates = [], []
    for asset in ordered:
        op = (
            _covered(asset, at, context, topology, context_rules["include_upstream_assets"])
            if context_rules["suppress_during_planned_operations"]
            else None
        )
        if op is not None:
            suppressed.append(asset)
            explanation.append(
                f"{asset} is inside planned operation {op.kind} on {op.asset_id} "
                f"({op.start:%Y-%m-%d %H:%M} to {op.end:%Y-%m-%d %H:%M}); it is not dispatched."
            )
        else:
            candidates.append(asset)

    ev = rules["evidence"]
    terms = [
        ScoreTerm(
            name="alarm_started",
            points=ev["alarm_started"],
            input="1 alarm start",
            rule="evidence.alarm_started",
        )
    ]
    repeats = min(
        alarm.earlier_starts_in_lookback * ev["repeat_alarm_points"], ev["repeat_alarm_cap"]
    )
    terms.append(
        ScoreTerm(
            name="repeated_alarms",
            points=repeats,
            input=f"{alarm.earlier_starts_in_lookback} earlier starts in {ev['lookback_h']} h",
            rule="evidence.repeat_alarm_points, capped at evidence.repeat_alarm_cap",
        )
    )
    age_h = (at - alarm.first_alarm_at).total_seconds() / 3600
    age = min(int(age_h // ev["age_step_h"]), ev["age_cap"])
    terms.append(
        ScoreTerm(
            name="evidence_age",
            points=age,
            input=f"{age_h:.1f} h since the first alarm",
            rule="one point per evidence.age_step_h, capped at evidence.age_cap",
        )
    )
    share = max(
        (topology.facts[a].consequence_share for a in candidates if a in topology.facts),
        default=0.0,
    )
    consequence = round(rules["consequence"]["points_max"] * share)
    worst = (
        max(candidates, key=lambda a: topology.facts[a].consequence_share, default=None)
        if candidates
        else None
    )
    terms.append(
        ScoreTerm(
            name="consequence",
            points=consequence,
            input=f"{share:.3f} of the field's wells flow through {worst}"
            if worst
            else "no candidate",
            rule="consequence.points_max times the largest consequence share among candidates",
        )
    )
    requested = sorted(set(candidates) & set(context.open_inspection_request_assets))
    terms.append(
        ScoreTerm(
            name="open_inspection_request",
            points=ev["open_inspection_request"] if requested else 0,
            input=", ".join(requested) or "none",
            rule="evidence.open_inspection_request",
        )
    )
    score = sum(t.points for t in terms)

    degraded = [s for s in alarm.evidence if s.degraded_quality and s.asset_id in candidates]
    if not ordered:
        action = Action.NEEDS_EVIDENCE
        explanation.append(
            "No evidence sensor could be tied to an asset, so more data is needed first."
        )
    elif not candidates:
        action = Action.NO_ACTION_PLANNED_OPERATION
    elif len(degraded) >= rules["data_quality"]["min_degraded_evidence_sensors"]:
        action = Action.CHECK_INSTRUMENTATION
        explanation.append(
            "Evidence sensors with degraded quality: "
            + ", ".join(s.tag for s in degraded)
            + ". Check instrumentation and communication before a field visit."
        )
    else:
        action = Action.FIELD_INSPECTION

    band: str | None = None
    respond: int | None = None
    if action in (Action.FIELD_INSPECTION, Action.CHECK_INSTRUMENTATION):
        band, respond = _band(score, rules["priority_bands"])
        explanation.append(
            f"Priority score {score} = "
            + " + ".join(f"{t.points} {t.name}" for t in terms)
            + f", band {band}"
            + (
                f", respond within {respond} h of simulated time."
                if respond
                else ", next scheduled visit."
            )
        )
    # Rules version 3: candidates are listed largest consequence first, so the work order targets
    # that asset. Python's sort is stable, so ties keep evidence order.
    candidates = sorted(
        candidates,
        key=lambda a: -(topology.facts[a].consequence_share if a in topology.facts else 0.0),
    )
    digest = hashlib.sha256(f"{alarm.alarm_id}|rules-v{rules['version']}".encode()).hexdigest()[:16]
    return Recommendation(
        recommendation_id=f"REC-{digest}",
        alarm_id=alarm.alarm_id,
        scenario_id=alarm.scenario_id,
        scenario_run_id=alarm.scenario_run_id,
        decided_at=at,
        action=action,
        candidate_assets=candidates,
        suppressed_assets=suppressed,
        priority_score=score,
        priority_band=band,
        respond_within_h=respond,
        terms=terms,
        explanation=explanation,
        rules_version=rules["version"],
        model_id=alarm.model_id,
        model_version=alarm.model_version,
        model_sha256=alarm.model_sha256,
    )
