# Diagnostic Milestone D1: gathering-line restriction diagnosis

Status: **preregistered, not started.** No case has been generated, no method written, and no result seen. Frozen plan: [`config/diagnostics/d1_preregistration.yaml`](../../config/diagnostics/d1_preregistration.yaml), version 1. Why: [diagnostic reset](diagnostic_reset.md) and [ADR 0020](../adr/0020-diagnostic-reset.md).

Everything in D1 is SYNTHETIC: fictional AETHER Field and its uncalibrated Gate 4 model. A D1 result says what a model-based diagnosis can do inside that model, not what it would do on a real field.

## Goal

> Given field telemetry, localize a gathering-system restriction, estimate its severity and production impact, and recommend the next diagnostic measurement with quantified uncertainty.

## What a diagnosis returns

For one case, at the diagnosis time, using only the allowed inputs:

| Output | Content |
|---|---|
| **Ranking** | A probability for each of the 15 pipes and for "no restriction", summing to 1 |
| **Evidence** | For each of the top candidates, the observations that support it and the ones that count against it, with their size relative to sensor noise |
| **Severity** | A point estimate and central 80% and 95% intervals, for the top candidate |
| **Production impact** | Lost field flow in sm³/s, as a point estimate with 80% and 95% intervals |
| **Next measurement** | One measurement from the menu, with the expected reduction in ranking uncertainty and the rationale |

After the recommended measurement's reading arrives, the diagnosis is updated and scored again.

## Scope

**In:** restrictions in one pipe (any of the 12 flowlines or 3 gathering segments), or none. Quasi-steady telemetry from the Gate 4 simulator, unmodified. Unknown well deliverability, sensor noise, compressor setpoint, and declared planned operations as nuisances.

**Excluded from D1:** work-order generation, approvals, routing, aerial evidence, cloud deployment, and frontend work. Also excluded: compressor faults, sensor faults as diagnosis targets, multiple simultaneous restrictions, and any real-field data.

## Cases

| Split | Cases | Use |
|---|---:|---|
| development | 300 | Building the method. Free to use. |
| calibration | 100 | Calibrating uncertainty. Free to use. |
| final_in_regime | 150 | **Untouched** until the method is frozen. Scored once. |
| final_held_out | 6 regimes × 40 | **Untouched** until the method is frozen. Scored once. |

In-regime restrictions occur on 12 of the 15 pipes at severity 0.10 to 0.60; 15% of cases have no restriction. The held-out regimes are high severity, three pipes never restricted in development (FL-A-06, FL-B-03, GS-TRUNK), high noise, deliverability outside the training range, compressor operation outside the training range, and degraded operations (shut-in wells and a telemetry dropout). Seeds are disjoint from every earlier gate.

## Measurement menu

| Measurement | Reading | Noise |
|---|---|---|
| Portable differential pressure across one pipe | 1-hour average | 200 Pa |
| Precision gauge at one node | 1-hour average | 300 Pa |
| Well test on one well | 4-hour test-separator flow | 0.0005 sm³/s |
| Shut-in test on one well | Every permanent sensor before and after a 2-hour shut-in | Permanent sensor noise |

The permanent sensors read with 2,000 Pa (pressure), 500 Pa (segment differential pressure), and 0.0015 sm³/s (flow) noise. Flowlines have no differential-pressure sensor of their own.

## Acceptance criteria

Scored on material restrictions (true impact at least 1% of field flow) unless stated. Thresholds were set without data. Where a criterion names the B1 baseline, the lower end of the 95% bootstrap interval of the difference must be above zero.

| Area | Criterion | In regime | Held-out regimes |
|---|---|---|---|
| Localization | Top-1: true pipe ranked first | ≥ 0.70 and beats B1 | ≥ 0.60 pooled, ≥ 0.55 in each regime |
| Localization | Top-3 | ≥ 0.90 | reported |
| No restriction | NONE ranked first on no-restriction cases | ≥ 0.80 | reported |
| No restriction | NONE ranked first on material restrictions | ≤ 0.10 | reported |
| Severity | Mean absolute error, where the true pipe is ranked first | ≤ 0.07 | reported |
| Impact | Within max(20% of truth, 0.5% of field flow) | ≥ 80% of cases | reported |
| Impact | Median relative error | ≤ 0.15 | reported |
| Uncertainty | Brier skill score against the uniform prior | ≥ 0.50 | reported |
| Uncertainty | Expected calibration error of the top probability | ≤ 0.10 | reported |
| Uncertainty | 80% interval coverage, severity and impact | 0.72 to 0.88 | 0.65 to 0.92 in each regime |
| Uncertainty | 95% interval coverage | 0.90 to 0.98 | reported |
| Measurement | Relative entropy reduction of the pipe ranking | ≥ 0.25 | reported |
| Measurement | Top-1 gain after the measurement | ≥ 0.08, interval above zero | reported |
| Measurement | Beats a random menu measurement | Interval above zero | reported |

**Outcome:** MET if every line holds; MET IN REGIME ONLY if every in-regime line holds and a held-out line fails; NOT MET otherwise. A NOT MET result is reported as such, as Gates 5 and 7 were.

**Baselines:** B0 ranks every hypothesis equally. B1 ranks pipes by the standardized residual of their pressure drop against the nominal Gate 4 model. Both are frozen in the preregistration.

## Keeping the final cases untouched

1. **Freeze before generation.** Final cases can't be generated until `config/diagnostics/d1_freeze.yaml` is committed. It must hold the method's commit, the preregistration's SHA-256, and the method configuration's SHA-256. The generator checks this and refuses otherwise.
2. **Truth stays out of diagnosis.** Case truth is written to its own directory. The diagnosis package can't import the generator or truth modules, which a test enforces. Its one entry point takes telemetry, the planned-operations calendar, the network design, and a measurement port. The port returns only the reading of a measurement the method asked for.
3. **One final run.** The final evaluation runs once through the attempt recorder, which keeps every attempt. A rerun is allowed only after a crash, with the cause stated.
4. **Logged changes.** Any change to the preregistration gets a new version and an entry with date, reason, and timing: before development results, after development results but before the freeze, after the freeze but before final results, or after final results.

## Not decided yet

The method is open. The preregistration fixes what is measured and how, not how the diagnosis works. A likely candidate is Bayesian inversion of the Gate 4 network model over pipe and severity, with nuisance parameters for well deliverability, and expected information gain for measurement choice. That choice is made in development and recorded in the freeze.
