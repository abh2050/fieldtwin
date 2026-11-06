# Numerical residual and convergence report

Generated from executed runs. Tests check its content, but not exact text, because iteration counts could differ by one between CPUs.

> **All values are `SYNTHETIC`.** AETHER Field is a fictional industrial production environment. These results come from a simplified physical model of fictional equipment. They are not real operating data, and the model is not a validated engineering simulator.

## Formulation

Unknowns are well flows. Pipe flows are exact sums of well flows, so junction mass balance holds by construction, and it is recomputed from stored results as an independent check. Newton solves the well equations, which are the gradient of a convex function. See the [field simulation specification](../../docs/product/field_simulation_spec.md).

## Convergence by scenario

| Scenario | Samples | Distinct states | Max Newton iterations | Max active-set passes | Max relative residual | Worst junction balance (sm3/s) | Inflow equation | Pipe equation |
|---|---:|---:|---:|---:|---|---|---|---|
| `AETHER-NET-NORMAL` | 2,016 | 1 | 4 | 1 | below 1e-12 | below 1e-12 | below 1e-09 | below 1e-09 |
| `AETHER-FAULT-001-NET` | 2,016 | 1,153 | 4 | 1 | below 1e-12 | below 1e-12 | below 1e-09 | below 1e-09 |
| `AETHER-NET-COMPRESSOR-DERATE` | 2,016 | 577 | 8 | 2 | below 1e-12 | below 1e-12 | below 1e-09 | below 1e-09 |
| `AETHER-NET-SENSOR-DRIFT` | 2,016 | 1 | 4 | 1 | below 1e-12 | below 1e-12 | below 1e-09 | below 1e-09 |
| `AETHER-NET-COMM-DROPOUT` | 2,016 | 1 | 4 | 1 | below 1e-12 | below 1e-12 | below 1e-09 | below 1e-09 |
| `AETHER-NET-PLANNED-SHUTDOWN` | 2,016 | 3 | 4 | 1 | below 1e-12 | below 1e-12 | below 1e-09 | below 1e-09 |

Solver limit: relative residual 1e-12, in at most 80 iterations. A state that doesn't converge raises an error and returns no result.

## Checks on every run

| Check | Limit | `NET-NORMAL` | `FAULT-001-NET` | `NET-COMPRESSOR-DERATE` | `NET-SENSOR-DRIFT` | `NET-COMM-DROPOUT` | `NET-PLANNED-SHUTDOWN` |
|---|---|---|---|---|---|---|---|
| `junction_mass_balance` | <= 1e-08 sm3/s | PASS | PASS | PASS | PASS | PASS | PASS |
| `well_inflow_equation` | <= 1e-06 relative | PASS | PASS | PASS | PASS | PASS | PASS |
| `pipe_flow_equation` | <= 1e-06 relative | PASS | PASS | PASS | PASS | PASS | PASS |
| `solver_converged` | <= 1e-12 relative | PASS | PASS | PASS | PASS | PASS | PASS |
| `no_reverse_flow` | >= 0 | PASS | PASS | PASS | PASS | PASS | PASS |
| `pressure_falls_along_flow` | no rise along flow | PASS | PASS | PASS | PASS | PASS | PASS |
| `wellhead_below_shut_in` | < 0 Pa margin | PASS | PASS | PASS | PASS | PASS | PASS |
| `idle_wells_have_zero_flow` | = 0 | PASS | PASS | PASS | PASS | PASS | PASS |
| `station_capacity_respected` | <= 1e-08 sm3/s | PASS | PASS | PASS | PASS | PASS | PASS |
| `suction_not_below_setpoint` | <= 0.001 Pa | PASS | PASS | PASS | PASS | PASS | PASS |
| `pressures_inside_envelope` | 300000 to 8000000 Pa abs | PASS | PASS | PASS | PASS | PASS | PASS |
| `mach_inside_envelope` | <= 0.3 | PASS | PASS | PASS | PASS | PASS | PASS |
| `reynolds_inside_envelope` | >= 4000 | PASS | PASS | PASS | PASS | PASS | PASS |
| `compression_ratio_inside_envelope` | <= 6.0 | PASS | PASS | PASS | PASS | PASS | PASS |
| `telemetry_fully_attributed` | every row attributed | PASS | PASS | PASS | PASS | PASS | PASS |
| `quality_matches_values` | good has a value, bad has none | PASS | PASS | PASS | PASS | PASS | PASS |
| `steady_before_onset` | 1 state before onset | n/a | PASS | PASS | n/a | n/a | PASS |

## Agreement with an independent solver

Nested bisection shares no code with the Newton solver.

| State | Quantity | Newton | Bisection | Difference |
|---|---|---:|---:|---:|
| All open | Total flow (sm3/s) | 7.118081 | 7.118081 | below 1e-06 |
| All open | MANIFOLD (Pa abs) | 1,720,182.5 | 1,720,182.5 | below 1 Pa |
| All open | HDR-A (Pa abs) | 1,903,667.0 | 1,903,667.0 | below 1 Pa |
| All open | HDR-B (Pa abs) | 1,911,849.5 | 1,911,849.5 | below 1 Pa |
| GS-A severity 0.65 | Total flow (sm3/s) | 6.500565 | 6.500565 | below 1e-06 |
| GS-A severity 0.65 | MANIFOLD (Pa abs) | 1,700,822.5 | 1,700,822.5 | below 1 Pa |
| GS-A severity 0.65 | HDR-A (Pa abs) | 2,244,708.9 | 2,244,708.9 | below 1 Pa |
| GS-A severity 0.65 | HDR-B (Pa abs) | 1,897,002.6 | 1,897,002.6 | below 1 Pa |

## Regression against the Gate 3 reference

The network reduced to one well and one segment, compared with the Gate 3 single-well model.

| Severity | Gate 3 flow (sm3/s) | Network flow (sm3/s) | Gate 3 wellhead (Pa abs) | Network wellhead (Pa abs) |
|---:|---:|---:|---:|---:|
| 0.0 | 0.675816 | 0.675816 | 2,171,427.40 | 2,171,427.40 |
| 0.275 | 0.670214 | 0.670214 | 2,181,615.85 | 2,181,615.85 |
| 0.55 | 0.612382 | 0.612382 | 2,282,935.99 | 2,282,935.99 |
| 0.7 | 0.424774 | 0.424774 | 2,569,432.20 | 2,569,432.20 |

## Edge cases, as executed

| State | Regime | Total flow (sm3/s) | HDR-B (Pa abs) | MANIFOLD (Pa abs) | Suction (Pa abs) |
|---|---|---:|---:|---:|---:|
| Every well shut in | NO_FLOW | 0.0000 | 1,600,000 | 1,600,000 | 1,600,000 |
| IV-B closed (branch isolated) | SETPOINT_CONTROLLED | 3.6968 | 3,450,000 | 1,633,287 | 1,600,000 |
| IV-STATION closed | NO_FLOW | 0.0000 | 3,450,000 | 3,450,000 | 1,600,000 |
| All compressors stopped | STOPPED | 0.0000 | 3,450,000 | 3,450,000 | 3,450,000 |
| Pad B shut in, valve open | SETPOINT_CONTROLLED | 3.6968 | 1,633,287 | 1,633,287 | 1,600,000 |
| Pad B shut in, valve closed | SETPOINT_CONTROLLED | 3.6968 | undetermined | 1,633,287 | 1,600,000 |

A closed section with no pressure source is reported as undetermined, with `BAD_NOT_MEASURABLE` telemetry, not given an invented value. Infeasible and unknown states raise errors, and tests cover them.

## What these numbers show

They show the model satisfies its own equations and that two independent solvers agree. They don't validate the model against any real gas system.
