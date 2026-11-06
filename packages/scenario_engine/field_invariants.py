"""Numerical and physical checks on a finished field run. A failure refuses the run."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .field_simulation import (
    BAD_COMM,
    BAD_NOT_MEASURABLE,
    GOOD,
    PROVENANCE,
    FieldRun,
    default_setup,
)
from .network_graph import SOURCE_PREFIX, EdgeType, NodeType

BALANCE_TOLERANCE = 1.0e-8
EQUATION_TOLERANCE = 1.0e-6
NOISE_BOUND_SIGMA = 6.0


class FieldInvariantViolation(ValueError):
    """A run broke a declared numerical or physical check."""


@dataclass(frozen=True)
class FieldCheck:
    name: str
    passed: bool
    measured: float | str
    limit: str


def _check(name: str, measured: float, limit: float, label: str) -> FieldCheck:
    return FieldCheck(name, bool(measured <= limit), float(measured), label)


def junction_balances(run: FieldRun) -> dict[str, np.ndarray]:
    """Inflow minus outflow at every junction and sample, recomputed from stored flows."""
    _, graph, _, _, _ = default_setup()
    truth = run.truth
    balances = {}
    for node in graph.nodes.values():
        if node.node_type in (
            NodeType.SITE,
            NodeType.RESERVOIR_BOUNDARY,
            NodeType.DISCHARGE_BOUNDARY,
        ):
            continue
        total = np.zeros(len(truth))
        for edge in graph.flow_edges():
            if edge.target == node.node_id:
                total += truth[f"truth_q_{edge.edge_id}"].to_numpy()
            if edge.source == node.node_id:
                total -= truth[f"truth_q_{edge.edge_id}"].to_numpy()
        balances[node.node_id] = total
    return balances


def equation_residuals(run: FieldRun) -> tuple[float, float]:
    """Relative errors in the inflow and pipe equations on every flowing element."""
    config, graph, model, _, _ = default_setup()
    truth = run.truth
    inflow_worst, pipe_worst = 0.0, 0.0
    for well, spec in model.wells.items():
        q = truth[f"truth_q_INFLOW:{well}"].to_numpy()
        flowing = q > 0
        if not flowing.any():
            continue
        wellhead = truth[f"truth_p_WH:{well}"].to_numpy()[flowing]
        expected = (
            spec.coefficient
            * (spec.shut_in_pa_abs**2 - wellhead**2) ** config.well_defaults.deliverability_exponent
        )
        inflow_worst = max(inflow_worst, float(np.max(np.abs(expected - q[flowing]) / q[flowing])))
    for edge in model.pipes:
        q = truth[f"truth_q_{edge.edge_id}"].to_numpy()
        flowing = q > 0
        if not flowing.any():
            continue
        column = f"truth_severity_{edge.edge_id}"
        severities = truth[column].to_numpy() if column in truth else np.zeros(len(truth))
        k = np.array(
            [model.segment_resistance(edge, float(s)) for s in np.unique(severities[flowing])]
        )
        lookup = dict(zip(np.unique(severities[flowing]), k, strict=True))
        resistance = np.array([lookup[s] for s in severities[flowing]])
        upstream = truth[f"truth_p_{edge.source}"].to_numpy()[flowing]
        downstream = truth[f"truth_p_{edge.target}"].to_numpy()[flowing]
        drop = upstream**2 - downstream**2
        pipe_worst = max(
            pipe_worst, float(np.max(np.abs(drop - resistance * q[flowing] ** 2) / drop))
        )
    return inflow_worst, pipe_worst


def check_field_run(run: FieldRun) -> list[FieldCheck]:
    config, graph, model, catalog, sensors = default_setup()
    truth, telemetry = run.truth, run.telemetry
    envelope = config.validity_envelope
    checks = []

    balances = junction_balances(run)
    worst = max(float(np.max(np.abs(v))) for v in balances.values())
    checks.append(
        _check("junction_mass_balance", worst, BALANCE_TOLERANCE, f"<= {BALANCE_TOLERANCE:g} sm3/s")
    )
    inflow, pipe = equation_residuals(run)
    checks.append(
        _check(
            "well_inflow_equation",
            inflow,
            EQUATION_TOLERANCE,
            f"<= {EQUATION_TOLERANCE:g} relative",
        )
    )
    checks.append(
        _check(
            "pipe_flow_equation", pipe, EQUATION_TOLERANCE, f"<= {EQUATION_TOLERANCE:g} relative"
        )
    )
    checks.append(
        _check(
            "solver_converged",
            float(truth["diag_relative_residual"].max()),
            config.solver.relative_residual_tolerance,
            f"<= {config.solver.relative_residual_tolerance:g} relative",
        )
    )
    flow_columns = [c for c in truth.columns if c.startswith("truth_q_")]
    lowest = float(truth[flow_columns].to_numpy().min())
    checks.append(FieldCheck("no_reverse_flow", lowest >= 0, lowest, ">= 0"))

    ordering_worst = 0.0
    for edge in graph.flow_edges():
        if edge.edge_type is EdgeType.WELL_INFLOW or edge.edge_type is EdgeType.COMPRESSION:
            continue
        flowing = truth[f"truth_q_{edge.edge_id}"].to_numpy() > 0
        drop = (truth[f"truth_p_{edge.source}"] - truth[f"truth_p_{edge.target}"]).to_numpy()[
            flowing
        ]
        if len(drop):
            ordering_worst = max(ordering_worst, float(np.max(-drop)))
    checks.append(
        FieldCheck(
            "pressure_falls_along_flow", ordering_worst <= 0, ordering_worst, "no rise along flow"
        )
    )

    shut_in_worst = float("-inf")
    for well, spec in model.wells.items():
        flowing = truth[f"truth_q_INFLOW:{well}"].to_numpy() > 0
        wellhead = truth[f"truth_p_WH:{well}"].to_numpy()[flowing]
        if len(wellhead):
            shut_in_worst = max(shut_in_worst, float(np.max(wellhead - spec.shut_in_pa_abs)))
    checks.append(
        FieldCheck("wellhead_below_shut_in", shut_in_worst < 0, shut_in_worst, "< 0 Pa margin")
    )

    idle_worst = 0.0
    for well in model.wells:
        status = truth[f"truth_status_{well}"].to_numpy()
        idle = status != "PRODUCING"
        if idle.any():
            idle_worst = max(
                idle_worst, float(np.max(truth[f"truth_q_INFLOW:{well}"].to_numpy()[idle]))
            )
    checks.append(FieldCheck("idle_wells_have_zero_flow", idle_worst == 0, idle_worst, "= 0"))

    capacities = np.array(
        [
            sum(
                model.capacity[u] * truth[f"truth_capacity_fraction_{u}"].to_numpy()[i]
                for u in model.capacity
            )
            for i in range(len(truth))
        ]
    )
    suction = truth["truth_p_COMP-SUCTION"].to_numpy()
    reference = config.compression.reference_suction_pa_abs
    excess = (
        truth["truth_total_flow"].to_numpy()
        - capacities * np.nan_to_num(suction, nan=reference) / reference
    )
    checks.append(
        _check("station_capacity_respected", float(np.max(excess)), 1e-8, "<= 1e-08 sm3/s")
    )
    running = ~np.isnan(suction)
    below = config.compression.suction_setpoint_pa_abs - suction[running]
    checks.append(
        FieldCheck(
            "suction_not_below_setpoint",
            float(np.max(below)) <= 1e-3,
            float(np.max(below)),
            "<= 0.001 Pa",
        )
    )

    pressure_columns = [c for c in truth.columns if c.startswith("truth_p_")]
    pressures = truth[pressure_columns].to_numpy(dtype=float)
    checks.append(
        FieldCheck(
            "pressures_inside_envelope",
            bool(
                np.nanmax(pressures) <= envelope.max_pressure_pa_abs
                and np.nanmin(pressures) >= envelope.min_pressure_pa_abs
            ),
            f"{np.nanmin(pressures):.0f} to {np.nanmax(pressures):.0f} Pa abs",
            f"{envelope.min_pressure_pa_abs:.0f} to {envelope.max_pressure_pa_abs:.0f} Pa abs",
        )
    )
    checks.append(
        _check(
            "mach_inside_envelope",
            float(truth["truth_max_mach"].max()),
            envelope.max_mach_number,
            f"<= {envelope.max_mach_number}",
        )
    )
    lowest_re = float(truth["truth_min_reynolds"].min())
    checks.append(
        FieldCheck(
            "reynolds_inside_envelope",
            lowest_re >= envelope.min_reynolds_number_when_flowing,
            lowest_re,
            f">= {envelope.min_reynolds_number_when_flowing:g}",
        )
    )
    ratio = float(config.compression.discharge_pa_abs / np.nanmin(suction))
    checks.append(
        _check(
            "compression_ratio_inside_envelope",
            ratio,
            config.compression.max_compression_ratio,
            f"<= {config.compression.max_compression_ratio}",
        )
    )

    expected_tags = {s.tag for s in sensors}
    rows_ok = (
        set(telemetry["provenance_class"]) == {PROVENANCE}
        and set(telemetry["tag"]) == expected_tags
        and set(telemetry["scenario_id"]) == {run.scenario.scenario_id}
        and set(telemetry["scenario_run_id"]) == {run.run_id}
        and set(telemetry["parameter_set_sha256"]) == {run.parameter_set_sha256}
        and telemetry["simulator_version"].notna().all()
    )
    checks.append(
        FieldCheck(
            "telemetry_fully_attributed",
            bool(rows_ok),
            f"{len(expected_tags)} tags",
            "every row attributed",
        )
    )
    good = telemetry["quality"] == GOOD
    bad_nulls = bool(
        telemetry.loc[good, "value"].notna().all() and telemetry.loc[~good, "value"].isna().all()
    )
    known = set(telemetry["quality"]) <= {GOOD, BAD_COMM, BAD_NOT_MEASURABLE}
    checks.append(
        FieldCheck(
            "quality_matches_values",
            bad_nulls and known,
            "checked",
            "good has a value, bad has none",
        )
    )

    if run.scenario.first_onset_s is not None and run.scenario.changes_physics:
        before = truth[truth["offset_s"] < run.scenario.first_onset_s]
        steady = before.filter(like="truth_q_").round(9).drop_duplicates()
        checks.append(
            FieldCheck(
                "steady_before_onset",
                len(steady) == 1,
                f"{len(steady)} state",
                "1 state before onset",
            )
        )
    return checks


def require_field_run(run: FieldRun) -> list[FieldCheck]:
    checks = check_field_run(run)
    failed = [c for c in checks if not c.passed]
    if failed:
        raise FieldInvariantViolation("; ".join(f"{c.name}: {c.measured}" for c in failed))
    return checks


__all__ = [
    "FieldCheck",
    "FieldInvariantViolation",
    "SOURCE_PREFIX",
    "check_field_run",
    "equation_residuals",
    "junction_balances",
    "require_field_run",
]
