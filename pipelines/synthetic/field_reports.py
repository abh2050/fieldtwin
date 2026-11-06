"""Generate Gate 4 reports from executed runs. Only the provenance report needs a database."""

from __future__ import annotations

import numpy as np

from packages.reconciliation.provenance import audit_provenance
from packages.repositories.database import REPO_ROOT, connect
from packages.scenario_engine import physics
from packages.scenario_engine.field_invariants import (
    check_field_run,
    equation_residuals,
    junction_balances,
)
from packages.scenario_engine.field_simulation import default_setup, simulate_by_id
from packages.scenario_engine.network_solver import NetworkState, solve_network
from packages.scenario_engine.propagation import BASELINE, PROPAGATION_CASES, compare
from packages.scenario_engine.reference_solver import reference_solve, single_well_network

FOLDER = REPO_ROOT / "reports" / "simulation"
DISCLOSURE = (
    "> **All values are `SYNTHETIC`.** AETHER Field is a fictional industrial production environment. These results "
    "come from a simplified physical model of fictional equipment. They are not real operating data, and the model "
    "is not a validated engineering simulator."
)
PA_TO_PSI = 0.00014503773773
DIRECTION = {1: "rises", -1: "falls", 0: "unchanged"}
DAY = 86400


def _header(title: str, intro: str) -> list[str]:
    return [f"# {title}", "", intro, "", DISCLOSURE, ""]


def _bound(value: float, limit: float = 1e-9) -> str:
    """Values near machine precision differ between CPUs, so they are stated as a bound."""
    return f"below {limit:g}" if abs(value) < limit else f"{value:.3e}"


def render_catalog() -> str:
    config, _, _, catalog, _ = default_setup()
    simulation = catalog.simulation
    lines = _header(
        "Scenario configuration catalog",
        "Generated from [`config/scenarios/aether_field_scenarios.yaml`](../../config/scenarios/aether_field_scenarios.yaml) and [`config/facility/aether_network.yaml`](../../config/facility/aether_network.yaml). A test fails if this file differs from a fresh run.",
    )
    lines += [
        "## Common settings",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| Random seed | {simulation.seed} |",
        f"| Sampling | {simulation.interval_s} s for {simulation.duration_s / DAY:.0f} days |",
        f"| Simulated clock starts | {simulation.simulated_epoch}, in the future so it can't pass for real operations |",
        f"| Simulator | {config.network.name}, version {config.network.version} |",
        "",
        "## Scenarios",
        "",
        "| Scenario | Name | Category | Target | Affected | Changes physics | Parameter set SHA-256 |",
        "|---|---|---|---|---|---|---|",
    ]
    for scenario in catalog.scenarios:
        run = simulate_by_id(scenario.scenario_id)
        lines.append(
            f"| `{scenario.scenario_id}` | {scenario.name} | {scenario.category.value} | {scenario.target_asset_id} | {scenario.affected_asset_id} | {'yes' if scenario.changes_physics else 'no'} | `{run.parameter_set_sha256[:16]}...` |"
        )
    lines += ["", "## Scheduled actions", ""]
    for scenario in catalog.scenarios:
        lines += [f"### `{scenario.scenario_id}`", "", scenario.description, ""]
        rows = []
        for fault in scenario.physical_faults:
            amount = (
                f"severity {fault.max_severity}"
                if fault.max_severity is not None
                else f"capacity fraction {fault.final_fraction}"
            )
            rows.append(
                f"| {fault.kind} | {fault.asset_id} | day {fault.onset_s / DAY:.2f} | ramp ends day {fault.full_s / DAY:.2f}, then holds | {amount} |"
            )
        for sensor in scenario.sensor_faults:
            amount = (
                f"{sensor.magnitude:g} Pa"
                if sensor.magnitude is not None
                else f"{sensor.rate_per_day:g} Pa per day"
            )
            rows.append(
                f"| {sensor.kind} | {sensor.tag} | day {sensor.onset_s / DAY:.2f} | continues to the end | {amount} |"
            )
        for comm in scenario.communication_faults:
            rows.append(
                f"| COMMUNICATION_DROPOUT | {comm.group} | day {comm.onset_s / DAY:.2f} | ends day {comm.end_s / DAY:.2f} | readings not received |"
            )
        for operation in scenario.planned_operations:
            rows.append(
                f"| {operation.kind} | {operation.asset_id} | day {operation.start_s / DAY:.2f} | ends day {operation.end_s / DAY:.2f} | planned |"
            )
        if rows:
            lines += [
                "| Action | Asset or tag | Starts | Duration | Amount |",
                "|---|---|---|---|---|",
                *rows,
                "",
            ]
        else:
            lines += ["No scheduled actions.", ""]
    lines += [
        "## Separation of fault kinds",
        "",
        "A scenario declares one category, and the contract refuses mixed ones. Sensor and communication faults are applied after the solve, so they can't change the physics, and a test confirms their truth tables equal the normal case.",
    ]
    return "\n".join(lines) + "\n"


def render_telemetry() -> str:
    _, _, _, catalog, sensors = default_setup()
    lines = _header(
        "Synthetic telemetry report",
        "Generated from executed runs. A test fails if this file differs from a fresh run.",
    )
    lines += [
        "## Instruments",
        "",
        f"{len(sensors)} instruments. Pressures use pascals internally, with the reference stated. Display units are separate and never enter the calculation.",
        "",
        "| Tag | Asset | Position | Reference | Unit | Display | Noise (1 sigma) |",
        "|---|---|---|---|---|---|---:|",
    ]
    lines += [
        f"| `{s.tag}` | {s.asset_id} | `{s.measurement_definition_id}` | {s.reference} | {s.unit} | {s.display_unit} | {s.noise_std:g} |"
        for s in sensors
    ]
    lines += [
        "",
        "## Telemetry fields",
        "",
        "| Field | Meaning |",
        "|---|---|",
        "| `offset_s`, `simulated_time` | Seconds from the start, and a simulated clock |",
        "| `tag`, `asset_id`, `sensor_position` | Which instrument, on which fictional asset, at which measurement point |",
        "| `value`, `unit`, `reference` | The reading, null when there isn't one |",
        "| `quality` | `GOOD`, `BAD_COMM_LOST`, or `BAD_NOT_MEASURABLE` |",
        "| `sensor_status` | `OK`, `COMM_LOST`, or `NOT_MEASURABLE`. A drifting sensor still says `OK`, because it doesn't know. |",
        "| `equipment_state` | Operating state of the asset at that sample |",
        "| `provenance_class`, `scenario_id`, `scenario_run_id`, `simulator_version`, `parameter_set_sha256` | Attribution on every row |",
        "",
        "Simulator truth is in a separate file, so telemetry can't leak the answer to a detector.",
        "",
        "## Runs",
        "",
        "| Scenario | Rows | Good | Comm lost | Not measurable | SHA-256 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for scenario in catalog.scenarios:
        run = simulate_by_id(scenario.scenario_id)
        counts = run.telemetry["quality"].value_counts()
        lines.append(
            f"| `{scenario.scenario_id}` | {len(run.telemetry):,} | {counts.get('GOOD', 0):,} | {counts.get('BAD_COMM_LOST', 0):,} | {counts.get('BAD_NOT_MEASURABLE', 0):,} | `{run.canonical_sha256()[:16]}...` |"
        )
    tags = [
        "A-03.PT-WH",
        "A-03.FT",
        "B-03.FT",
        "HDR-A.PT-NET",
        "MANIFOLD.PT",
        "GS-A.DPT-NET",
        "COMP-SUCTION.PT",
        "C-01.FT",
        "C-02.FT",
    ]
    lines += [
        "",
        "## Mean readings over the final day",
        "",
        "Pressures in Pa, gauge or differential, and flows in sm3/s. These are noisy sensor readings, including any sensor fault.",
        "",
        "| Scenario | " + " | ".join(f"`{t}`" for t in tags) + " |",
        "|---|" + "---:|" * len(tags),
    ]
    for scenario in catalog.scenarios:
        frame = simulate_by_id(scenario.scenario_id).telemetry
        last = frame[frame["offset_s"] >= 6 * DAY]
        means = last.groupby("tag")["value"].mean()
        cells = [f"{means[t]:.3f}" if t.endswith(".FT") else f"{means[t]:,.0f}" for t in tags]
        lines.append(f"| `{scenario.scenario_id}` | " + " | ".join(cells) + " |")
    lines += [
        "",
        "The sensor scenario differs from normal on `A-03.PT-WH` because that transmitter is drifting, while its flow is unchanged. That difference is what a later detector would need to separate from a physical fault.",
        "",
        "## Limits",
        "",
        "- Noise is independent Gaussian. Real instruments also have correlated noise, deadband, and rate limits.",
        "- A dropout is a clean gap, with no repeated last values or late arrivals.",
        "- Pressures respond instantly to state changes, because the model is quasi-steady.",
    ]
    return "\n".join(lines) + "\n"


def render_propagation() -> str:
    lines = _header(
        "Cross-asset fault propagation",
        "Each expected direction is derived from the asset's place in the declared topology, before results are read. It is then compared with the coupled solve. A test fails if this file differs from a fresh run, or if any direction disagrees.",
    )
    total = 0
    matched = 0
    sections = []
    for scenario_id, (title, _, offset) in PROPAGATION_CASES.items():
        results = compare(scenario_id)
        total += len(results)
        matched += sum(r.matches for r in results)
        section = [
            f"## {title}",
            "",
            f"`{scenario_id}` against `{BASELINE}`, at day {offset / DAY:.2f}. Flows in sm3/s, and pressures in Pa absolute.",
            "",
            "| Asset | Quantity | Baseline | Faulted | Change | Expected | Observed | Why |",
            "|---|---|---:|---:|---:|---|---|---|",
        ]
        for r in results:
            digits = ".4f" if "low" in r.effect.quantity else ",.0f"
            percent = f"{r.percent:+.2f}%" if not np.isnan(r.percent) else "n/a"
            section.append(
                f"| {r.effect.asset_id} | {r.effect.quantity} | {r.baseline:{digits}} | {r.faulted:{digits}} | {percent} "
                f"| {DIRECTION[r.effect.direction]} | {DIRECTION[r.observed_direction]} | {r.effect.why} |"
            )
        sections += [*section, ""]
    lines += [
        "## Result",
        "",
        f"**{matched} of {total} topology-based predictions matched the coupled solve in direction.** This confirms the solver and the topology reasoning agree with each other. It doesn't show that a real gathering system would behave this way, and magnitudes depend on chosen parameters.",
        "",
        "## How one fault reaches other assets",
        "",
        "1. **Restriction in GS-A.** Pad A's header pressure rises, so every Pad A well loses drawdown and flow. Less gas enters the trunk, which lowers its friction loss, so manifold pressure falls. Pad B then discharges into a lower pressure and gains flow. Suction stays at setpoint, so compressors see only the smaller total.",
        "2. **Capacity loss on C-01.** Once arrivals exceed capacity, suction floats above setpoint. That pressure carries back through the trunk and manifold to every well on both pads, and the other units take a larger share.",
        "3. **Isolation of Pad B.** Its wells stop, and the trunk carries about half the gas. Lower friction lets Pad A wells produce more. Stopping C-04 at the same time doesn't limit flow, because arrivals fell by more than its capacity.",
        "",
        "The model is quasi-steady, so these effects appear in the same sample. Real pressure transients take time to travel, and that isn't modeled.",
        "",
        *sections,
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_numerics() -> str:
    config, _, model, catalog, _ = default_setup()
    lines = _header(
        "Numerical residual and convergence report",
        "Generated from executed runs. Tests check its content, but not exact text, because iteration counts could differ by one between CPUs.",
    )
    lines += [
        "## Formulation",
        "",
        "Unknowns are well flows. Pipe flows are exact sums of well flows, so junction mass balance holds by construction, and it is recomputed from stored results as an independent check. Newton solves the well equations, which are the gradient of a convex function. See the [field simulation specification](../../docs/product/field_simulation_spec.md).",
        "",
        "## Convergence by scenario",
        "",
        "| Scenario | Samples | Distinct states | Max Newton iterations | Max active-set passes | Max relative residual | Worst junction balance (sm3/s) | Inflow equation | Pipe equation |",
        "|---|---:|---:|---:|---:|---|---|---|---|",
    ]
    for scenario in catalog.scenarios:
        run = simulate_by_id(scenario.scenario_id)
        truth = run.truth
        states = len({scenario.state_at(int(o)) for o in truth["offset_s"]})
        worst = max(float(np.abs(v).max()) for v in junction_balances(run).values())
        inflow, pipe = equation_residuals(run)
        lines.append(
            f"| `{scenario.scenario_id}` | {len(truth):,} | {states:,} | {truth['diag_newton_iterations'].max()} | {truth['diag_active_set_passes'].max()} "
            f"| {_bound(float(truth['diag_relative_residual'].max()), 1e-12)} | {_bound(worst, 1e-12)} | {_bound(inflow)} | {_bound(pipe)} |"
        )
    lines += [
        "",
        f"Solver limit: relative residual {config.solver.relative_residual_tolerance:g}, in at most {config.solver.max_iterations} iterations. A state that doesn't converge raises an error and returns no result.",
        "",
        "## Checks on every run",
        "",
    ]
    scenarios = catalog.scenarios
    names = list(
        dict.fromkeys(
            c.name for s in scenarios for c in check_field_run(simulate_by_id(s.scenario_id))
        )
    )
    lines += [
        "| Check | Limit | "
        + " | ".join(f"`{s.scenario_id.replace('AETHER-', '')}`" for s in scenarios)
        + " |",
        "|---|---|" + "---|" * len(scenarios),
    ]
    results = {
        s.scenario_id: {c.name: c for c in check_field_run(simulate_by_id(s.scenario_id))}
        for s in scenarios
    }
    for name in names:
        limit = next(
            results[s.scenario_id][name].limit for s in scenarios if name in results[s.scenario_id]
        )
        cells = [
            ("PASS" if results[s.scenario_id][name].passed else "FAIL")
            if name in results[s.scenario_id]
            else "n/a"
            for s in scenarios
        ]
        lines.append(f"| `{name}` | {limit} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Agreement with an independent solver",
        "",
        "Nested bisection shares no code with the Newton solver.",
        "",
        "| State | Quantity | Newton | Bisection | Difference |",
        "|---|---|---:|---:|---:|",
    ]
    for label, severity in (("All open", {}), ("GS-A severity 0.65", {"GS-A": 0.65})):
        solved = solve_network(model, NetworkState(tuple(severity.items())))
        reference = reference_solve(model, config.compression.suction_setpoint_pa_abs, severity)
        lines.append(
            f"| {label} | Total flow (sm3/s) | {solved.total_flow:.6f} | {reference['total_flow']:.6f} | {_bound(solved.total_flow - reference['total_flow'], 1e-6)} |"
        )
        for node in ("MANIFOLD", "HDR-A", "HDR-B"):
            difference = solved.pressure_pa_abs[node] - reference[node]
            lines.append(
                f"| {label} | {node} (Pa abs) | {solved.pressure_pa_abs[node]:,.1f} | {reference[node]:,.1f} | {_bound(difference, 1.0)} Pa |"
            )
    single, gate3 = single_well_network()
    lines += [
        "",
        "## Regression against the Gate 3 reference",
        "",
        "The network reduced to one well and one segment, compared with the Gate 3 single-well model.",
        "",
        "| Severity | Gate 3 flow (sm3/s) | Network flow (sm3/s) | Gate 3 wellhead (Pa abs) | Network wellhead (Pa abs) |",
        "|---:|---:|---:|---:|---:|",
    ]
    for level in (0.0, 0.275, 0.55, 0.7):
        old = physics.solve(gate3, np.array([level]))
        new = solve_network(single, NetworkState((("GS-A", level),) if level else ()))
        lines.append(
            f"| {level} | {old.gas_flow_sm3_per_s[0]:.6f} | {new.edge_flow_sm3_per_s['INFLOW:A-03']:.6f} | {old.wellhead_pressure_pa_abs[0]:,.2f} | {new.pressure_pa_abs['WH:A-03']:,.2f} |"
        )
    wells = sorted(model.wells)
    pad_b = frozenset(w for w in wells if w.startswith("B"))
    cases = [
        ("Every well shut in", NetworkState(shut_in_wells=frozenset(wells))),
        ("IV-B closed (branch isolated)", NetworkState(closed_valves=frozenset({"IV-B"}))),
        ("IV-STATION closed", NetworkState(closed_valves=frozenset({"IV-STATION"}))),
        (
            "All compressors stopped",
            NetworkState(compressor_fraction=tuple((u, 0.0) for u in model.capacity)),
        ),
        ("Pad B shut in, valve open", NetworkState(shut_in_wells=pad_b)),
        (
            "Pad B shut in, valve closed",
            NetworkState(closed_valves=frozenset({"IV-B"}), shut_in_wells=pad_b),
        ),
    ]
    lines += [
        "",
        "## Edge cases, as executed",
        "",
        "| State | Regime | Total flow (sm3/s) | HDR-B (Pa abs) | MANIFOLD (Pa abs) | Suction (Pa abs) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for label, state in cases:
        solution = solve_network(model, state)
        p = solution.pressure_pa_abs
        show = lambda v: "undetermined" if np.isnan(v) else f"{v:,.0f}"  # noqa: E731
        lines.append(
            f"| {label} | {solution.regime.value} | {solution.total_flow:.4f} | {show(p['HDR-B'])} | {show(p['MANIFOLD'])} | {show(p['COMP-SUCTION'])} |"
        )
    lines += [
        "",
        "A closed section with no pressure source is reported as undetermined, with `BAD_NOT_MEASURABLE` telemetry, not given an invented value. Infeasible and unknown states raise errors, and tests cover them.",
        "",
        "## What these numbers show",
        "",
        "They show the model satisfies its own equations and that two independent solvers agree. They don't validate the model against any real gas system.",
    ]
    return "\n".join(lines) + "\n"


def render_provenance(conn) -> str:
    lines = _header(
        "Provenance validation",
        "Generated by `make field-reports` from the local canonical database, after loading real batches and recording all runs.",
    )
    total, complete, parameters, versions = conn.execute(
        """SELECT count(*), count(*) FILTER (WHERE chain_complete), count(DISTINCT parameter_set_sha256),
                  count(DISTINCT (simulator_name, simulator_version))
           FROM v_synthetic_provenance_chain"""
    ).fetchone()
    lines += [
        "## Result",
        "",
        f"**{complete} of {total} synthetic observations have a complete chain** to a fictional asset, sensor, scenario, run, simulator version, and parameter set.",
        "",
        "## By run",
        "",
        "| Run | Simulator | Series | Complete | Assets | Sensors | Parameter set |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in conn.execute(
        """SELECT scenario_run_id, simulator_name, simulator_version, count(*), count(*) FILTER (WHERE chain_complete),
                  count(DISTINCT asset_id), count(DISTINCT sensor_tag_id), min(parameter_set_sha256)
           FROM v_synthetic_provenance_chain GROUP BY 1, 2, 3 ORDER BY 1"""
    ):
        lines.append(
            f"| `{row[0]}` | {row[1]} v{row[2]} | {row[3]} | {row[4]} | {row[5]} | {row[6]} | `{row[7][:16]}...` |"
        )
    links = conn.execute(
        """SELECT o.source_system_id, l.relationship_type, l.verification_status, l.provenance_class, count(*)
           FROM asset_observation_links l JOIN observations o USING (observation_id) GROUP BY 1, 2, 3, 4"""
    ).fetchall()
    lines += [
        "",
        "## Links to assets",
        "",
        "| Observation source | Relationship | Status | Provenance | Count |",
        "|---|---|---|---|---:|",
    ]
    lines += [f"| {r[0]} | `{r[1]}` | {r[2]} | {r[3]} | {r[4]} |" for r in links]
    mappings = conn.execute("SELECT count(*) FROM scenario_mappings").fetchone()[0]
    three_w = conn.execute(
        "SELECT count(*) FROM asset_observation_links l JOIN observations o USING (observation_id) WHERE o.source_system_id = 'petrobras_3w'"
    ).fetchone()[0]
    lines += [
        "",
        "## Cross-domain leakage",
        "",
        f"- 3W observations linked to any asset: **{three_w}**.",
        f"- Source telemetry mapped into a scenario: **{mappings}**.",
        "",
        "## Provenance audit",
        "",
        "| Rule | Violations |",
        "|---|---:|",
    ]
    lines += [f"| {f.rule} | {f.violations} |" for f in audit_provenance(conn)]
    lines += [
        "",
        "## Enforcement",
        "",
        "The chain is enforced in the database (ADR 0015). Tests in `tests/provenance/test_application_role.py` and `tests/integration/test_field_db.py` attempt to break it.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    FOLDER.mkdir(parents=True, exist_ok=True)
    (FOLDER / "scenario_catalog.md").write_text(render_catalog())
    (FOLDER / "synthetic_telemetry.md").write_text(render_telemetry())
    (FOLDER / "fault_propagation.md").write_text(render_propagation())
    (FOLDER / "numerical_residuals.md").write_text(render_numerics())
    with connect() as conn:
        (FOLDER / "provenance_validation.md").write_text(render_provenance(conn))
    print(f"wrote 5 reports to {FOLDER.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
