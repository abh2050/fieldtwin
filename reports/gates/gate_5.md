# Gate 5 report: anomaly detection, benchmark evaluation, and uncertainty

**Status: CI_STATUS_PLACEHOLDER**

Date: 2026-11-09, revised after technical review. Branch: `gate-5`. Full output of the final local rebuild: [`gate_5_execution_log.txt`](gate_5_execution_log.txt). Every experiment attempt is recorded in [`attempts/`](../experiments/attempts/).

> **Two evidence classes, never pooled.** Petrobras 3W results are OBSERVED benchmark evidence from recorded offshore oil wells, labeled by their publisher. AETHER results are SYNTHETIC experiments on a fictional, uncalibrated model. Nothing here is field-validated detection performance, and neither track says anything about the other.

> **The holdouts aren't pristine.** Review found three defects after both holdouts had been read. They were fixed and every result regenerated. The current holdout numbers come from corrected code run on holdout data already read several times, so treat them as a check of the corrected pipeline, not an untouched estimate.

## Headline

- **3W, recorded data:** no method shows detection skill that holds up.
    - On development wells, no method's skill interval excludes zero.
    - On the holdout, logistic regression detects 8 of 40 events and starts no false alarm on a normal row. Its skill above chance is 0.20, with an interval of 0.08 to 0.77, the only 3W interval to exclude zero.
    - That result rests on a scoring rule. The model spends 7.5% of normal time in alarm, over the 5% limit, because two alarms start in unlabeled leading rows, which aren't scored, and run on into normal operation. Scoring those rows as normal gives 2 false alarms and skill 0.07 (−0.05 to 0.65).
- **AETHER, synthetic:** detection works in-regime. Three methods are statistically tied there: logistic regression at 0.57, gradient boosting at 0.50, and static limits at 0.38. The declared rule picks the simplest, static limits.
    - On held-out regimes, static limits fall to −0.02. They detect nothing when compressor conditions or deliverability move outside training, and they spend 29% of normal time in alarm.
    - Gradient boosting, 0.33 (0.21 to 0.45), and rolling deviation, 0.22 (0.10 to 0.35), hold up best.
- **Thresholds don't transfer to unseen wells or regimes.** Thresholds were set to keep normal time in alarm under 5% on validation data. Methods anchored to training levels overran that badly on new wells and on shifted operating points.

## Acceptance criteria

| # | Criterion | Result | Evidence |
|---:|---|---|---|
| 1 | 3W labels audited, including the 43 ambiguous class-9 instances | **Met** | All 498 instances graded. The 43 have no event-labeled row, nothing authoritative resolves them, and they're excluded from both sides of every primary metric. [Label audit](../experiments/3w_label_audit.md) |
| 2 | Evaluation splits are leakage-safe | **Met** | Split by well, checked in code and tests. Overlapping instances hold identical rows, and metrics count each well and time once. A random split would have overstated average precision: 0.95 by instance and 1.00 by row, against 0.81 by well. |
| 3 | Baseline and ML methods run on actual data | **Met** | Static limits, rolling deviation, logistic regression, isolation forest, and gradient boosting, on 299 recorded 3W instances and 272 AETHER cases |
| 4 | AETHER includes held-out scenario variations | **Met** | 8 regimes and 112 cases, never used in fitting or threshold setting |
| 5 | Both tracks produce independent reports | **Met** | [3W benchmark](../experiments/3w_benchmark.md) and [AETHER benchmark](../experiments/aether_synthetic_benchmark.md) |
| 6 | False alarms and detection measured with explicit definitions | **Met** | Rules in `config/experiments/gate5_evaluation.yaml`, now version 3. Sample-level and event-level metrics are separate. |
| 7 | Inference runs without ground-truth fault state | **Met** | The contracts have no field for truth and refuse extra fields. Inference code imports neither the simulator nor the labels, which a test checks. Batch and streaming scores agree for all 10 models. |
| 8 | Model artifacts and experiments are reproducible | REPRO_PLACEHOLDER |
| 9 | Numerical reliability tests and timeout protections exist | **Met** | 210 of 210 stress runs completed with matching hashes. Nonconvergence, infeasible state, timeout, and crash were each forced and classified correctly. Logistic regression now refuses an unconverged fit. [Reliability stress](../simulation/reliability_stress.md) |
| 10 | Gate 0–4 regression tests pass | REGRESSION_PLACEHOLDER |
| 11 | CI passes on the feature branch | CI_PLACEHOLDER |
| 12 | Limitations and unsupported claims disclosed | **Met** | See [Limitations](#limitations) |

## Review findings and what changed

| Finding | Response | Effect on results |
|---|---|---|
| 1. Events ended at the last scored row, not the last event-labeled row | Fixed, with a test of an event followed by normal rows | None. No event in this data returns to normal before its instance ends. |
| 2. Logistic regression stopped at 500 iterations | Limit raised to 5,000. Reaching it is now an error, and iterations are recorded for every fit. All fits converge within 640 iterations. | Four of six fits had stopped early. Capped coefficients differed by up to 10% from converged ones, and validation rankings correlated 0.975 to 0.998. |
| 3. Threshold search stopped at the median | Now covers the whole score range, with a test of a feasible threshold below the median | Thresholds and results moved for several methods. |
| 4. Holdout retries weren't independently auditable | The AETHER holdout is described here as exposed before its first persisted run. Every stage now runs through a recorder that keeps each attempt, including failures, with result hashes before and after. | Process only |
| 5. Bootstrap description was wrong | Corrected below: all 9 holdout wells are resampled, and 6 of them contain events. | Text only |

Fixing finding 2 exposed a further bug. Taking the log of `predict_proba` still gave minus infinity, so some windows tied. Classifier scores now come from decision values.

Examining the new 3W holdout result exposed the unlabeled-leading-row effect described in the headline. It's reported as a sensitivity check rather than a rule change.

### Selections, before and after

| Track | Before review | After review |
|---|---|---|
| 3W | Logistic regression, tied with isolation forest | Logistic regression, tied with isolation forest |
| AETHER | Logistic regression, tied with gradient boosting | **Static limits**, tied with logistic regression and gradient boosting |

### Earlier changes

These were made before either holdout was read, and both are recorded in the configuration and [ADR 0017](../../docs/adr/0017-detection-evaluation-design.md).

- **Version 2 of the rules.** The thresholds walk down from the top under a time-in-alarm limit, and selection uses skill above chance. Version 1 accepted alarms that never turn off, and long events inflated recall by chance, so its 0.95 AETHER recall is permanently superseded.
- **A fix for repeated file names.** Some generated 3W files reuse names across class folders. That fix changed only one training variant.

### Holdout exposure

- **First holdout attempts:** they crashed in bookkeeping before writing results. The 3W attempt printed nothing. The AETHER attempt printed its 8 regime results to a log. That log wasn't consulted, but this can't be independently verified, so the AETHER holdout counts as exposed from then on.
- **Since the review:** both holdouts have been rerun after code changes, and all those runs are in the attempt records.

## 3W results (OBSERVED)

Development: four folds, 159 events. Holdout: 9 wells, 40 events on 6 of them, and 213 hours of normal operation.

| Method | Development skill (95% interval) | Holdout events | Holdout false alarms per hour | Holdout skill (95% interval) | Leading rows as normal: skill | Holdout time in alarm |
|---|---|---:|---:|---|---:|---:|
| Static limits | −0.00 (−0.05 to 0.03) | 1 of 40 | 0.000 | 0.03 (0.00 to 0.18) | −0.23 | 0.079 |
| Rolling deviation | 0.13 (−0.16 to 0.34) | 14 of 40 | 0.028 | 0.04 (−0.19 to 0.86) | −0.01 | 0.019 |
| **Logistic regression** (preferred) | 0.16 (−0.08 to 0.34) | 8 of 40 | 0.000 | 0.20 (0.08 to 0.77) | 0.07 | 0.075 |
| Isolation forest | −0.10 (−0.31 to 0.21) | 7 of 40 | 0.009 | 0.03 (−0.15 to 0.63) | −0.30 | 0.331 |
| Gradient boosting | −0.05 (−0.17 to 0.07) | 3 of 40 | 0.009 | −0.07 (−0.16 to 0.28) | −0.10 | 0.008 |

- **Selection:** in development, rolling deviation exceeded the budget, at 0.067 false alarms per hour. Logistic regression had the best skill among the methods within budget, tied with isolation forest.
- **Intervals:** the holdout intervals resample all 9 holdout wells together, and only 6 contain events. With so few wells the intervals are themselves unstable, so the upper bounds near 0.8 mean little.
- **Per class:** every holdout class sits on one or two wells, so no per-class recall is reported.
- **Ambiguous instances:** counting the 43 as events adds 10 holdout events, and logistic regression detects 2 of them. See [robustness](../experiments/robustness.md).
- **Training variants:** none of the gradient boosting variants clearly helps.

## AETHER results (SYNTHETIC)

In-regime: 20 events. Held-out regimes pooled: 80 events.

| Method | In-regime events | In-regime skill (95% interval) | Held-out events | Held-out skill (95% interval) | Held-out time in alarm |
|---|---:|---|---:|---|---:|
| **Static limits** (preferred) | 12 of 20 | 0.38 (0.11 to 0.62) | 25 of 80 | −0.02 (−0.14 to 0.11) | 0.286 |
| Rolling deviation | 17 of 20 | 0.29 (0.11 to 0.46) | 55 of 80 | 0.22 (0.10 to 0.35) | 0.047 |
| Logistic regression | 17 of 20 | 0.57 (0.27 to 0.87) | 47 of 80 | 0.18 (0.02 to 0.34) | 0.217 |
| Isolation forest | 11 of 20 | −0.01 (−0.25 to 0.21) | 42 of 80 | −0.02 (−0.15 to 0.11) | 0.060 |
| Gradient boosting | 10 of 20 | 0.50 (0.27 to 0.71) | 33 of 80 | 0.33 (0.21 to 0.45) | 0.013 |

- **Simplest isn't safest here.** The selection rule picks the simplest of the tied methods, and static limits are the least robust under shift. Rolling deviation compares each series with its own past, so it was least affected. The rule worked as declared, but the result shows it doesn't account for robustness.
- **Detection delay:** this is simulation time from a quasi-steady model with faults ramping over days. It says nothing about physical pressure waves or real detection latency.
- **Gate 4 scenarios:** static limits detected the restriction and the derate in the six accepted runs, missed the sensor drift, and raised 2 alarms during planned shutdown.

## Inference

The streaming contract takes asset identity, measurement definitions, timestamped readings with quality, and the model's identity and version. It returns everything the directive lists, with provenance `INFERRED` and the input class `OBSERVED` or `SYNTHETIC`.

On one Apple Silicon machine with one thread:
- **Latency:** p95 per window from 0.06 ms (AETHER static limits) to 4.4 ms (AETHER isolation forest). Most of it is contract validation.
- **Memory:** process peak RSS of 250 to 330 MB, mostly the Python runtime.
- **Artifacts:** from 2 KB to 3.1 MB.

Details: [inference performance](../experiments/inference_performance.md).

## Reliability

Hardening added:
- **Bounded walks:** both graph walks are bounded, on top of the existing 80-iteration Newton limit and 16-pass active-set limit. Gate 4's six hashes are unchanged.
- **Process guard:** every run happens in a child process with a hard timeout, a stack dump just before it, and JSON progress lines.
- **Separate outcomes:** nonconvergence, infeasible states, envelope refusals, timeouts, and crashes are reported apart.
- **Attempt recorder:** every experiment stage now runs through one, which keeps each attempt.

All 272 AETHER cases and 210 stress runs went through the guard without a failure.

**The Gate 4 hang is not claimed fixed.** Its cause was never found, and it didn't recur in 30 repeats of the work that was running when it happened.

## Evidence

EVIDENCE_PLACEHOLDER

## Required reports

| Report | Evidence class |
|---|---|
| [3W label audit](../experiments/3w_label_audit.md) | OBSERVED |
| [3W benchmark](../experiments/3w_benchmark.md) | OBSERVED |
| [AETHER synthetic benchmark](../experiments/aether_synthetic_benchmark.md) | SYNTHETIC |
| [Model comparison](../experiments/model_comparison.md) | Both, never pooled |
| [Robustness](../experiments/robustness.md) | Both, never pooled |
| [Inference performance](../experiments/inference_performance.md) | Both, never pooled |
| [Reliability stress](../simulation/reliability_stress.md) | SYNTHETIC |

The architecture diagram has a page, `detection-evaluation`, exported to [`detection_evaluation.png`](../experiments/detection_evaluation.png). Decisions are in [ADR 0017](../../docs/adr/0017-detection-evaluation-design.md).

## Limitations

1. **No field validation.** Nothing here shows how any method would perform on a real field, AETHER's or anyone else's.
2. **No reliable 3W skill.** The single interval that excludes zero depends on how unlabeled rows are scored, on a holdout no longer unread. It doesn't support a claim of detection on unseen wells.
3. **The 3W data is a subset.** 498 of 2,228 files, chosen by sorted name, which favors lower well numbers and earlier dates. Normal operation covers only 9 wells.
4. **Intervals are wide and unstable.** The holdout resamples 9 wells, 6 of which contain events.
5. **Chance level is approximate.** It treats false alarms as a Poisson process at the measured rate.
6. **Unlabeled rows aren't scored.** Alarms that start in them aren't counted as false alarms, so methods that alarm early in a file look better than they are. A sensitivity check reports the alternative.
7. **No per-well adaptation.** Thresholds are global. A deployed system would usually calibrate each well, and this design deliberately doesn't credit that.
8. **The selection rule ignores robustness.** Picking the simplest tied method chose static limits on AETHER, the least robust method under shift.
9. **AETHER is one fictional model.** Results show detection of this simulator's behavior only, and delay is simulation time.
10. **Rules were revised twice.** Version 2 came after development results and before either holdout. Version 3 came after review and after both holdouts had been read.
11. **The ambiguous 3W instances stay unresolved.** The two doctoral theses in the 3W repository were not read.
12. **Reproduction is one machine.** ML scores were reproduced on one machine. CI checks simulator hashes, not model scores, across platforms.

## Scope kept out

No drone image analysis, maintenance optimization, frontend, or AWS deployment. No paid model calls or AWS resources. No 3W event was mapped to an AETHER asset. Gate 5 isn't merged.
