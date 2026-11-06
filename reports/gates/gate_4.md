# Gate 4 report: AETHER Field multi-asset simulation

**Status: ALL 10 ACCEPTANCE TESTS MET, stopped for technical review.** The work is on branch `gate-4`, with a [successful CI run](https://github.com/abh2050/fieldtwin/actions/runs/42141073855). It isn't merged.

Date: 2026-11-05 (log timestamps are UTC, 2026-11-06). Branch: `gate-4`. Full output of the final local rebuild: [`gate_4_execution_log.txt`](gate_4_execution_log.txt).

> AETHER Field is fictional. Its equipment relationships and telemetry are `SYNTHETIC`, not real operating data. This is a simplified model, not a validated engineering simulator, and no parameter is calibrated.

## Acceptance tests

| # | Test | Result | Evidence |
|---:|---|---|---|
| 1 | Complete fictional asset network is constructed | **Met** | 12 wells, 2 pads, 3 gathering segments, 3 valves, 4 compressors, 3 sites. The stored graph has 32 nodes and 36 edges. |
| 2 | Physical connectivity is internally consistent | **Met** | Validated in Python and enforced by the database. Cycles, wrong connection types, dead ends, and impossible pipe lengths are refused. |
| 3 | Coupled flow satisfies declared conservation constraints | **Met** | Worst junction balance is below 1e-12 sm3/s in all six scenarios, and Newton agrees with a separate bisection solver. |
| 4 | All six operating scenarios execute | **Met** | 2,016 samples and 78,624 telemetry rows each, with every declared check passing. |
| 5 | Telemetry is correctly attributed and versioned | **Met** | 242 of 242 synthetic observations have a complete chain to asset, sensor, scenario, run, simulator version, and parameter set. |
| 6 | Cross-asset consequences are demonstrated | **Met** | 81 of 81 direction predictions made from topology match the coupled solve. |
| 7 | Regression and new tests pass | **Met** | See [Test results](#test-results). |
| 8 | CI passes on the feature branch | **Met** | [All 9 jobs passed](https://github.com/abh2050/fieldtwin/actions/runs/42141073855) on commit `202bc51`. | |
| 9 | Reports contain executed numerical results | **Met** | Generated from runs. Tests fail if the catalog, telemetry, or propagation report differs from a fresh run. |
| 10 | Limitations are disclosed | **Met** | See [Limitations](#limitations). |

## Required evidence

| Item | Location |
|---|---|
| Asset topology diagram | [`aether_asset_topology.png`](../simulation/diagrams/aether_asset_topology.png) |
| Physical network diagram | [`aether_physical_network.png`](../simulation/diagrams/aether_physical_network.png) |
| Simulation sequence diagram | [`simulation_sequence.png`](../simulation/diagrams/simulation_sequence.png) |
| Synthetic telemetry report | [`synthetic_telemetry.md`](../simulation/synthetic_telemetry.md) |
| Scenario configuration catalog | [`scenario_catalog.md`](../simulation/scenario_catalog.md) |
| Numerical residual and convergence report | [`numerical_residuals.md`](../simulation/numerical_residuals.md) |
| Cross-asset fault propagation report | [`fault_propagation.md`](../simulation/fault_propagation.md) |
| Provenance validation report | [`provenance_validation.md`](../simulation/provenance_validation.md) |
| Test evidence | This report and [`gate_4_execution_log.txt`](gate_4_execution_log.txt) |
| Editable diagrams | [`docs/architecture.drawio`](../../docs/architecture.drawio), pages 5 to 7 |
| Technical documentation | [Field simulation specification](../../docs/product/field_simulation_spec.md) and [ADR 0016](../../docs/adr/0016-coupled-field-network.md) |

## Executed results

Values are from the model at day 7, or at day 3.25 for the shutdown, against the normal run.

| Quantity | Normal | GS-A restriction (0.65) | C-01 at 30% capacity | Pad B isolated, C-04 stopped |
|---|---:|---:|---:|---:|
| Total flow (sm3/s) | 7.1181 | 6.5006 | 7.0540 | 3.6968 |
| HDR-A pressure (Pa abs) | 1,903,667 | 2,244,709 | 1,922,827 | 1,836,841 |
| Manifold pressure (Pa abs) | 1,720,183 | 1,700,823 | 1,744,799 | 1,633,287 |
| Suction pressure (Pa abs) | 1,600,000 | 1,600,000 | 1,628,633 | 1,600,000 |
| Well A-03 flow (sm3/s) | 0.6415 | 0.5488 | 0.6368 | 0.6575 |

The restriction on GS-A also changes Pad B, which isn't on the restricted path. Each Pad B well gains 0.54% to 0.84% in flow, because the shared manifold pressure falls by 1.13%. Independent well simulators couldn't show that.

**Convergence.** The most Newton iterations in any scenario was 8, and the most active-set passes was 2, both in the compressor derate. Every other scenario took at most 4 iterations and 1 pass. All relative residuals are below the 1e-12 limit.

**Gate 3 regression.** Reduced to one well and one segment, the network matches the Gate 3 model to the 6 decimal flow and 2 decimal pressure figures reported, at severities 0, 0.275, 0.55, and 0.7. Gate 3's own golden hashes are unchanged.

**Sensor and communication faults.** These scenarios leave simulator truth identical to the normal run. `AETHER-NET-COMM-DROPOUT` loses 2,160 of 78,624 readings, all marked `BAD_COMM_LOST`.

**Cross-domain leakage.** 0 of the 3W observations link to any asset, and 0 source telemetry series map into a scenario. All 96 attempts to map a 3W sensor onto an AETHER measurement were refused.

## Test results

From the final rebuild, with 0 failed steps out of 28.

| Suite | Passed | Failed |
|---|---:|---:|
| Offline tests | 430 | 0 |
| Database tests on fixtures | 228 | 0 |
| Tests on real acquired data | 23 | 0 |
| CI commands in a clean copy: unit | 423 | 0 |
| CI commands in a clean copy: contract | 7 | 0 |
| CI commands in a clean copy: Postgres integration | 79 | 0 |
| CI commands in a clean copy: provenance | 149 | 0 |

Ruff, the format check, and mypy pass. Canonical validation shows 21 checks and 0 failures.

| Required test | Where |
|---|---|
| Junction mass balance | `test_mass_balances_at_every_junction_in_any_state`, `test_junction_balances_are_small_everywhere`, `test_broken_mass_balance_is_caught_and_the_run_refused` |
| Pressure and flow constraints | `test_no_reverse_flow_and_pressure_falls_along_flow_in_any_state`, `test_station_never_exceeds_capacity_or_falls_below_setpoint` |
| Solver convergence | `test_newton_agrees_with_independent_nested_bisection`, `test_unconverged_solve_raises_instead_of_returning_a_result` |
| Physical-unit consistency | `test_gauge_sensors_read_one_ambient_below_absolute`, `test_differential_sensor_needs_no_ambient_and_matches_pressures`, `test_sensors_match_their_declared_measurement_definitions` |
| Deterministic replay | `test_scenarios_are_deterministic`, `test_same_state_gives_exactly_the_same_answer`, `test_noise_streams_are_tied_to_tags` |
| Sensor mapping validity | `test_series_link_to_the_asset_each_sensor_is_on`, `test_every_row_is_attributed_and_versioned` |
| Fault onset consistency | `test_nothing_happens_before_the_known_onset`, `test_physics_responds_at_the_declared_onset`, `test_events_stay_in_the_synthetic_domain_with_known_onsets` |
| No cross-domain leakage | `test_no_field_configuration_or_output_refers_to_3w`, `test_field_records_touch_no_source_data`, `test_physical_graph_cannot_reference_a_real_asset_or_claim_observed` |
| Reproducibility across environments | `test_run_matches_the_recorded_hash`, in the CI job `simulation-reproducibility` |
| Gate 3 regression | `test_network_reduces_to_the_gate_3_single_well_reference`, plus the golden hashes in `test_physics.py` |
| Edge cases | `test_zero_flow_when_every_well_is_shut_in`, `test_closed_valve_isolates_its_pad_and_it_equalizes`, `test_closed_section_with_no_source_is_undetermined_not_invented`, `test_infeasible_or_unknown_states_are_refused` |
| Property-based testing | 6 Hypothesis tests in `tests/unit/test_network_solver.py`, derandomized |

## What went wrong along the way

1. **The first solver was replaced.** It solved for junction pressures and passed all six scenarios, but property tests found it failing to converge in other states, because the pipe law's slope is infinite at zero pressure drop. The well-flow form replaced it. Newton iterations fell from about 21 to 4. Five of six hashes were unchanged, and the restriction hash changed because the old solver stopped at a looser tolerance. See [ADR 0016](../../docs/adr/0016-coupled-field-network.md).
2. **The first capacity value made the normal case capacity limited.** Each compressor was raised to 2.10 sm3/s, so normal operation sits at setpoint. This is a design choice in a fictional model, not a finding.
3. **Static pressure was wrong behind a closed station valve.** This is fixed and now tested through connected sections.
4. **The `wellhead_below_shut_in` check had a wrong initial value.** This is fixed.
5. **A local shell run hung for more than 500 s, and the cause wasn't determined.** It stopped at an inline propagation script and didn't reproduce in a script file or in any later run. An unbounded loop in the static pressure code was bounded as a precaution, but nothing shows that loop was the cause.
6. **Diagram layout failed review twice.** Connectors ran through boxes on the topology page, and an access route overlapped the trunk on the network page. The final PNGs were inspected by eye.

## Changes to existing tests and reports

| Change | Reason |
|---|---|
| Tag counts changed to 27 + 4 + 37 = 68 | Gate 4 adds 37 field sensors |
| Synthetic observation count changed from 8 to 8 + 234 | Gate 4 adds 6 runs of 39 series |
| Added a complete-chain test on the real database | Gate 4 extends the provenance requirement |
| Asset count in `entity_resolution.md` changed from 27 to 47 | Gate 4 adds assets |
| Rejected 3W mappings in `semantic_validation.md` changed from 56 to 96 | More AETHER measurements to refuse |

## Limitations

1. **Not a validated engineering simulator.** No result has been compared with a real gas system or a commercial simulator. The tests show that the model meets its own equations and that two solvers agree.
2. **Direction checks show consistency, not truth.** The 81 predictions and the solver both come from the same assumed physics.
3. **Quasi-steady.** Effects appear in the same sample. There's no line pack, transit time, or pressure wave, so this data can't support conclusions about detection timing against real transients.
4. **Simplified physics.** Single-phase gas, isothermal flow, constant `Z` and friction factor, no elevation, no liquids or hydrates, no reservoir depletion, and fully open chokes.
5. **The compressor is a boundary, not a map.** Compression work isn't computed, discharge is fixed, and flow is shared in proportion to capacity.
6. **Tree network only.** Looped gathering would need a different formulation.
7. **Declared parameters.** Well values are design choices, so differences between wells carry no statistical meaning. Six runs with one seed are not a dataset for detection performance.
8. **Telemetry is idealized.** Noise is independent Gaussian. Dropouts are clean gaps, with no repeated values or late arrivals.
9. **Some faults don't reach some sensors.** The restriction leaves suction at setpoint, so suction telemetry shows nothing. Whether any fault can be detected hasn't been evaluated, because that belongs to a later gate.
10. **PostGIS runs emulated.** Local PostGIS uses a linux/amd64 image on Apple Silicon.
11. **Reproducibility covers three platforms.** Those are Linux x86, Linux ARM, and macOS ARM, with locked dependencies. Other CPUs or library versions aren't covered, and hashes round values to stay above platform noise.
12. **One unexplained local hang.** See item 5 above.

## Scope kept out

No anomaly-detection benchmark, drone image analysis, maintenance optimization, frontend, or AWS deployment. No paid model calls or AWS resources. No 3W event was mapped to an AETHER asset. Gate 5 was not started. Gate 4 is not merged.

## CI

[Run 42141073855](https://github.com/abh2050/fieldtwin/actions/runs/42141073855), on commit `202bc51`, passed all 9 jobs: `lint-and-types`, `unit`, `contract`, `postgres-integration`, `provenance-invariants`, `dependency-and-credential-scan`, and `simulation-reproducibility` on `ubuntu-24.04`, `ubuntu-24.04-arm`, and `macos-15` (arm64).

The three reproducibility jobs compare the six output hashes with the same recorded values, so the hashes match on Linux x86, Linux ARM, and macOS ARM.

The [first run](https://github.com/abh2050/fieldtwin/actions/runs/42140895856) was cancelled. GitHub refused the `macos-14` runner before the job started, so that platform hadn't been tested. The matrix now uses `macos-15`. The other 8 jobs passed in that run.

This section was added after that run, so the commit holding it has its own CI run, which is visible on the branch.
