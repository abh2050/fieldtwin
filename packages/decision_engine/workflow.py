"""Simulated work orders with explicit state transitions and an audit trail.

The engine may only recommend. Approving, rejecting, or requesting evidence needs a maintenance
supervisor. Nothing here actuates equipment: a work order is a record for fictional assets.

Actors are labelled by kind. `HUMAN` is a person. `SCRIPTED_DEMO` is a scripted step in a demonstration
run that stands in for a person and is reported as such; it is never counted as a human decision.
`SYSTEM` is the decision engine, which may create recommendations and nothing else.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .rules import Action, Recommendation


class Status(StrEnum):
    RECOMMENDED = "RECOMMENDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    COMPLETED = "COMPLETED"


class Decision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    RESUBMIT = "RESUBMIT"
    COMPLETE = "COMPLETE"


class ActorKind(StrEnum):
    HUMAN = "HUMAN"
    SCRIPTED_DEMO = "SCRIPTED_DEMO"
    SYSTEM = "SYSTEM"


# (from, decision) -> to. Anything else is refused.
TRANSITIONS: dict[tuple[Status, Decision], Status] = {
    (Status.RECOMMENDED, Decision.APPROVE): Status.APPROVED,
    (Status.RECOMMENDED, Decision.REJECT): Status.REJECTED,
    (Status.RECOMMENDED, Decision.REQUEST_EVIDENCE): Status.NEEDS_EVIDENCE,
    (Status.NEEDS_EVIDENCE, Decision.RESUBMIT): Status.RECOMMENDED,
    (Status.NEEDS_EVIDENCE, Decision.REJECT): Status.REJECTED,
    (Status.APPROVED, Decision.COMPLETE): Status.COMPLETED,
}
SUPERVISOR = "MAINTENANCE_SUPERVISOR"
SUPERVISOR_DECISIONS = {Decision.APPROVE, Decision.REJECT, Decision.REQUEST_EVIDENCE}


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actor_id: str = Field(min_length=1)
    kind: ActorKind
    role: str


class TransitionError(ValueError):
    pass


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    work_order_id: str
    sequence: int
    actor: Actor
    decision: Decision | Literal["CREATE"]
    before: Status | None
    after: Status
    justification: str
    at: datetime


class WorkOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_order_id: str
    recommendation_id: str
    scenario_id: str
    scenario_run_id: str
    asset_id: str
    action: Action
    priority_band: str
    priority_score: int
    respond_within_h: int | None
    status: Status = Status.RECOMMENDED
    history: list[AuditEvent] = []
    provenance_class: Literal["SYNTHETIC"] = "SYNTHETIC"

    def _record(
        self, actor: Actor, decision, before, after, justification: str, at: datetime
    ) -> None:
        self.history.append(
            AuditEvent(
                work_order_id=self.work_order_id,
                sequence=len(self.history),
                actor=actor,
                decision=decision,
                before=before,
                after=after,
                justification=justification,
                at=at,
            )
        )

    def apply(self, decision: Decision, actor: Actor, justification: str, at: datetime) -> Status:
        target = TRANSITIONS.get((self.status, decision))
        if target is None:
            raise TransitionError(f"{decision} is not allowed from {self.status}")
        if actor.kind is ActorKind.SYSTEM:
            raise TransitionError("the decision engine may recommend only; a person must decide")
        if decision in SUPERVISOR_DECISIONS and actor.role != SUPERVISOR:
            raise TransitionError(f"{decision} needs the {SUPERVISOR} role")
        if not justification.strip():
            raise TransitionError("every decision needs a justification")
        if self.history and at < self.history[-1].at:
            raise TransitionError("decisions must be recorded in time order")
        before = self.status
        self.status = target
        self._record(actor, decision, before, target, justification, at)
        return target


def create_work_order(recommendation: Recommendation, engine: Actor) -> WorkOrder:
    """Only dispatchable recommendations become work orders, always starting as RECOMMENDED."""
    if engine.kind is not ActorKind.SYSTEM:
        raise TransitionError("work orders are created by the decision engine")
    if recommendation.action not in (Action.FIELD_INSPECTION, Action.CHECK_INSTRUMENTATION):
        raise TransitionError(f"{recommendation.action} does not create a work order")
    if recommendation.priority_band is None or not recommendation.candidate_assets:
        raise TransitionError("a work order needs a priority band and a candidate asset")
    digest = hashlib.sha256(recommendation.recommendation_id.encode()).hexdigest()[:12]
    order = WorkOrder(
        work_order_id=f"WO-{digest}",
        recommendation_id=recommendation.recommendation_id,
        scenario_id=recommendation.scenario_id,
        scenario_run_id=recommendation.scenario_run_id,
        asset_id=recommendation.candidate_assets[0],
        action=recommendation.action,
        priority_band=recommendation.priority_band,
        priority_score=recommendation.priority_score,
        respond_within_h=recommendation.respond_within_h,
    )
    order._record(
        engine,
        "CREATE",
        None,
        Status.RECOMMENDED,
        f"Created from {recommendation.recommendation_id}",
        recommendation.decided_at,
    )
    return order
