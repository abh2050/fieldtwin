"""Explain cross-asset effects from the declared topology, then compare with the coupled solve.

Each expected effect is derived from where an asset sits relative to the fault, without looking at
results. Reports and tests then compare the expected direction with the computed one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .field_simulation import FieldRun, default_setup, simulate_by_id
from .network_graph import WELLHEAD_PREFIX, NetworkGraph

BASELINE = "AETHER-NET-NORMAL"
_NEGLIGIBLE = 1e-9


@dataclass(frozen=True)
class ExpectedEffect:
    asset_id: str
    quantity: str
    column: str
    direction: int
    why: str


@dataclass(frozen=True)
class ObservedEffect:
    effect: ExpectedEffect
    baseline: float
    faulted: float

    @property
    def change(self) -> float:
        return self.faulted - self.baseline

    @property
    def percent(self) -> float:
        return 100.0 * self.change / self.baseline if self.baseline else float("nan")

    @property
    def observed_direction(self) -> int:
        scale = max(abs(self.baseline), abs(self.faulted), 1.0)
        return 0 if abs(self.change) <= _NEGLIGIBLE * scale else int(np.sign(self.change))

    @property
    def matches(self) -> bool:
        return self.observed_direction == self.effect.direction


def _wells_above(graph: NetworkGraph, node: str) -> list[str]:
    return sorted(
        n.removeprefix(WELLHEAD_PREFIX)
        for n in graph.upstream_of(node)
        if n.startswith(WELLHEAD_PREFIX)
    )


def restriction_effects(segment: str) -> list[ExpectedEffect]:
    """A restriction in a pad's segment, with suction held at setpoint."""
    config, graph, model, _, _ = default_setup()
    edge = graph.edges[segment]
    near = _wells_above(graph, edge.source)
    far = sorted(set(model.wells) - set(near))
    others = [s for s in config.segments if s.target == edge.target and s.id != segment]
    trunk = graph.downstream_edge(edge.target)
    assert trunk is not None
    effects = [
        ExpectedEffect(edge.source, "Header pressure", f"truth_p_{edge.source}", 1,
                       f"Upstream of the restriction. More resistance in {segment} needs a higher inlet pressure to pass gas."),
        ExpectedEffect(segment, "Flow", f"truth_q_{segment}", -1,
                       "Its wells can't push as much gas against the added resistance."),
        ExpectedEffect(edge.target, "Manifold pressure", f"truth_p_{edge.target}", -1,
                       f"Less gas reaches {trunk.edge_id}, so its friction loss falls and the manifold relaxes toward suction."),
        ExpectedEffect(trunk.edge_id, "Flow", f"truth_q_{trunk.edge_id}", -1,
                       "The rise from the other pad is smaller than the loss from the restricted pad."),
        ExpectedEffect(model.suction, "Suction pressure", f"truth_p_{model.suction}", 0,
                       "Recycle holds setpoint, because capacity still exceeds arrivals."),
    ]  # fmt: skip
    for well in near:
        effects.append(ExpectedEffect(well, "Gas flow", f"truth_q_INFLOW:{well}", -1,
                                      "Shares the restricted path, so higher backpressure reduces its drawdown."))  # fmt: skip
        effects.append(ExpectedEffect(well, "Wellhead pressure", f"truth_p_{WELLHEAD_PREFIX}{well}", 1,
                                      "Backpressure from its header rises."))  # fmt: skip
    for other in others:
        effects.append(ExpectedEffect(other.source, "Header pressure", f"truth_p_{other.source}", -1,
                                      "Not on the restricted path. It discharges into a lower manifold pressure."))  # fmt: skip
        effects.append(ExpectedEffect(other.id, "Flow", f"truth_q_{other.id}", 1,
                                      "The lower manifold pressure lets this branch pass more gas."))  # fmt: skip
    for well in far:
        effects.append(ExpectedEffect(well, "Gas flow", f"truth_q_INFLOW:{well}", 1,
                                      "Not on the restricted path. It gains from the lower manifold pressure."))  # fmt: skip
        effects.append(ExpectedEffect(well, "Wellhead pressure", f"truth_p_{WELLHEAD_PREFIX}{well}", -1,
                                      "Its header pressure fell with the manifold."))  # fmt: skip
    for unit in model.capacity:
        effects.append(ExpectedEffect(unit, "Unit flow", f"truth_q_{unit}", -1,
                                      "Total arrivals fell, and units share flow by available capacity."))  # fmt: skip
    return effects


def derate_effects(compressor: str) -> list[ExpectedEffect]:
    """Capacity falls below arrivals, so the station can't hold setpoint."""
    _, _, model, _, _ = default_setup()
    effects = [
        ExpectedEffect(model.suction, "Suction pressure", f"truth_p_{model.suction}", 1,
                       "Arrivals exceed capacity at setpoint, so suction floats up until flow and capacity agree."),
        ExpectedEffect("MANIFOLD", "Manifold pressure", "truth_p_MANIFOLD", 1,
                       "Higher suction raises the pressure the trunk discharges into."),
        ExpectedEffect(compressor, "Unit flow", f"truth_q_{compressor}", -1,
                       "This unit lost capacity."),
    ]  # fmt: skip
    for unit in model.capacity:
        if unit != compressor:
            effects.append(ExpectedEffect(unit, "Unit flow", f"truth_q_{unit}", 1,
                                          f"Takes a larger share as {compressor} loses capacity, within its own limit."))  # fmt: skip
    for well in model.wells:
        effects.append(ExpectedEffect(well, "Gas flow", f"truth_q_INFLOW:{well}", -1,
                                      "Higher pressure anywhere on the shared path reduces every well's drawdown."))  # fmt: skip
        effects.append(ExpectedEffect(well, "Wellhead pressure", f"truth_p_{WELLHEAD_PREFIX}{well}", 1,
                                      "Backpressure rises through the shared trunk and manifold."))  # fmt: skip
    return effects


def isolation_effects(segment: str, stopped_unit: str) -> list[ExpectedEffect]:
    """A pad is isolated by its valve, and a compressor is stopped, during planned work."""
    _, graph, model, _, _ = default_setup()
    edge = graph.edges[segment]
    isolated = _wells_above(graph, edge.source)
    remaining = sorted(set(model.wells) - set(isolated))
    effects = [
        ExpectedEffect(segment, "Flow", f"truth_q_{segment}", -1, "Its isolation valve is closed."),
        ExpectedEffect("MANIFOLD", "Manifold pressure", "truth_p_MANIFOLD", -1,
                       "The shared trunk carries about half the gas, so its friction loss falls."),
        ExpectedEffect(model.suction, "Suction pressure", f"truth_p_{model.suction}", 0,
                       "Arrivals fell by more than the stopped unit's capacity, so setpoint still holds."),
        ExpectedEffect(stopped_unit, "Unit flow", f"truth_q_{stopped_unit}", -1, "This unit is stopped."),
    ]  # fmt: skip
    for well in isolated:
        effects.append(ExpectedEffect(well, "Gas flow", f"truth_q_INFLOW:{well}", -1, "Its outlet path is closed."))  # fmt: skip
    for well in remaining:
        effects.append(ExpectedEffect(well, "Gas flow", f"truth_q_INFLOW:{well}", 1,
                                      "It discharges into a lower manifold pressure while the other pad is out."))  # fmt: skip
    return effects


PROPAGATION_CASES = {
    "AETHER-FAULT-001-NET": ("Restriction in GS-A", lambda: restriction_effects("GS-A"), 604500),
    "AETHER-NET-COMPRESSOR-DERATE": (
        "C-01 capacity falls to 30%",
        lambda: derate_effects("C-01"),
        604500,
    ),
    "AETHER-NET-PLANNED-SHUTDOWN": (
        "IV-B closed, C-04 stopped",
        lambda: isolation_effects("GS-B", "C-04"),
        280800,
    ),
}


def _row_at(run: FieldRun, offset_s: int):
    return run.truth[run.truth["offset_s"] == offset_s].iloc[0]


def compare(scenario_id: str) -> list[ObservedEffect]:
    _, build, offset = PROPAGATION_CASES[scenario_id]
    baseline = _row_at(simulate_by_id(BASELINE), offset)
    faulted = _row_at(simulate_by_id(scenario_id), offset)
    return [ObservedEffect(e, float(baseline[e.column]), float(faulted[e.column])) for e in build()]
