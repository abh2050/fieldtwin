# Diagnostic Milestone D1: gathering-line restriction diagnosis

Status: **preregistered, not started.** No case has been generated, no method written, and no result seen. Frozen plan: [`config/diagnostics/d1_preregistration.yaml`](../../config/diagnostics/d1_preregistration.yaml), version 2. Why: [diagnostic reset](diagnostic_reset.md) and [ADR 0020](../adr/0020-diagnostic-reset.md).

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

An action is one measurement type with one target. There are 55 actions in all.

| Measurement | Targets | Reading | Noise | Duration | Burden |
|---|---|---|---|---:|---|
| Portable differential pressure | 15 pipes | 1-hour average across the pipe | 200 Pa | 1 h | Non-intrusive |
| Precision gauge | 16 nodes with a pressure sensor | 1-hour average | 300 Pa | 1 h | Non-intrusive |
| Well test | 12 wells | 4-hour test-separator flow | 0.0005 sm³/s | 4 h | Flow diverted, production continues |
| Shut-in test | 12 wells | Every permanent sensor before and after a 2-hour shut-in | Permanent sensor noise | 2 h | Production interrupted |

Every action is valid except a well test or shut-in test on a well that the planned-operations calendar shows shut in at the diagnosis time. The random comparator draws one valid action uniformly per case, with a frozen seed. Burden is reported separately for recommended and random actions: the mix of types, mean duration, the share that interrupt production, deferred production, and entropy reduction per measurement-hour. A secondary comparison draws the random action from the same type as the recommendation, which separates choosing an informative type from choosing a good target.

The permanent sensors read with 2,000 Pa (pressure), 500 Pa (segment differential pressure), and 0.0015 sm³/s (flow) noise. Flowlines have no differential-pressure sensor of their own.

## Acceptance criteria

Scored on material restrictions (true impact at least 1% of field flow) unless stated. Thresholds were set without data. Where a criterion names the B1 baseline, the lower end of the 95% bootstrap interval of the difference must be above zero.

| Area | Criterion | In regime | Held-out regimes |
|---|---|---|---|
| Localization | Top-1: true pipe ranked first | ≥ 0.70 and beats B1 | ≥ 0.60 pooled, ≥ 0.55 in each regime |
| Localization | Top-3 | ≥ 0.90 | reported |
| No restriction | NONE ranked first on no-restriction cases | ≥ 0.80 | reported |
| No restriction | NONE ranked first on material restrictions | ≤ 0.10 | reported |
| Joint success | True pipe first, severity within 0.10, and impact within tolerance, all in the same case; mislocalized cases count as failures | ≥ 0.55 | reported |
| Impact | Within max(20% of truth, 0.5% of field flow) | ≥ 80% of cases | reported |
| Impact | Median relative error | ≤ 0.15 | reported |
| Uncertainty | Brier skill score against the generator-matched climatology, over all cases | ≥ 0.50 | reported |
| Uncertainty | Expected calibration error of the top probability | ≤ 0.10 | reported |
| Uncertainty | 80% interval coverage, severity and impact | 0.72 to 0.88 | 0.65 to 0.92 in each regime |
| Uncertainty | 95% interval coverage | 0.90 to 0.98 | reported |
| Measurement | Relative entropy reduction of the pipe ranking | ≥ 0.25 | reported |
| Measurement | Top-1 gain after the measurement | ≥ 0.08, interval above zero | reported |
| Measurement | Beats a random menu measurement | Interval above zero | reported |

**Secondary diagnostics, reported but not accepted on:** severity mean absolute error where the true pipe is ranked first (target 0.07 or less), every line on each held-out regime, pipe-level results, Brier skill against the uniform prior, and the same-type random comparison.

**Minimum support.** Counted on the final cases after the material filter, before scoring:

| Count | Minimum | Expected before the filter |
|---|---:|---:|
| In-regime primary cases | 90 | about 128 |
| In-regime no-restriction cases | 15 | about 22 |
| Primary cases per held-out regime | 20 | about 34 |
| Pooled held-out primary cases | 120 | about 204 |
| Primary cases per pipe, for any pipe-level result | 8 | about 10 in-regime |

A result below its minimum is INCONCLUSIVE and never counts toward MET.

**Outcome:** support is checked first. INCONCLUSIVE if in-regime support is short, whatever the scores. NOT MET if any in-regime line fails. MET IN REGIME ONLY if every in-regime line holds and a held-out line fails or a held-out count is short, with each failing or inconclusive regime named. MET only if every line holds with full support. A NOT MET result is reported as such, as Gates 5 and 7 were.

**Baselines:** B0 is the generator's own class frequencies, known exactly from the preregistration: 0.15 for no restriction, 0.85 / 12 for each in-regime pipe, and 0 for the three never-restricted pipes. The unseen-pipes regime is scored against the same in-regime climatology, since that is all a developer could know, with that regime's own frequencies reported alongside. B1 ranks pipes by the standardized residual of their pressure drop against the nominal Gate 4 model. A uniform prior is reported for reference only. All are frozen in the preregistration.

## Keeping the final cases untouched

1. **Freeze before generation.** Final cases can't be generated until `config/diagnostics/d1_freeze.yaml` is committed. It must hold the method's commit, the preregistration's SHA-256, and the method configuration's SHA-256. The generator checks this and refuses otherwise.
2. **Truth stays out of diagnosis.** Case truth is written to its own directory. The diagnosis package can't import the generator or truth modules, which a test enforces. Its one entry point takes telemetry, the planned-operations calendar, the network design, and a measurement port. The port returns only the reading of a measurement the method asked for.
3. **One final run.** The final evaluation runs once through the attempt recorder, which keeps every attempt. A rerun is allowed only after a crash, with the cause stated.
4. **Logged changes.** Any change to the preregistration gets a new version and an entry with date, reason, and timing: before development results, after development results but before the freeze, after the freeze but before final results, or after final results.

## Change log

| Version | Date | Timing | Change |
|---:|---|---|---|
| 1 | 2026-11-10 | Before any case, method, or result | Initial preregistration |
| 2 | 2026-11-10 | `BEFORE_DEVELOPMENT_RESULTS`, after technical review | Brier baseline is now the generator-matched climatology, not a uniform prior. The random comparator is defined over 55 enumerated actions, with burden reported separately. A joint success rate is an acceptance line, and conditional severity error is secondary. Minimum sample support is frozen, with INCONCLUSIVE below it. |

## Not decided yet

The method is open. The preregistration fixes what is measured and how, not how the diagnosis works. A likely candidate is Bayesian inversion of the Gate 4 network model over pipe and severity, with nuisance parameters for well deliverability, and expected information gain for measurement choice. That choice is made in development and recorded in the freeze.
