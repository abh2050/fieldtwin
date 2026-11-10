# ADR 0017: Detection evaluation fixed before fitting, with two separate tracks

**Status:** Accepted and implemented in Gate 5.

## Context

Gate 5 compares anomaly detectors on two kinds of data that must never be pooled. Petrobras 3W holds recorded offshore events, labeled by its publisher. AETHER holds synthetic telemetry from an uncalibrated fictional model. It's easy to fool yourself with either: tune on the test data, split so the same well appears on both sides, or pick a metric that rewards an always-on alarm.

## Decision

**Rules come first.** The event-matching rules, false-alarm budget, selection rule, splits, and AETHER held-out regimes are in `config/experiments/gate5_evaluation.yaml` and `config/experiments/aether_benchmark.yaml`. They were committed before any model was fitted. A change has to be recorded in the file and disclosed in the gate report.

**3W is split by well.** Every instance and window from a well stays on one side, because instances from one well overlap in time and hold identical rows. One fold of wells is the holdout, and four development folds choose a method. Each fold sets its threshold on validation wells.

**Ambiguous labels stay out.** The 43 class-9 instances with no event label are on neither side of any primary metric. They aren't counted as events or as normal. Sensitivity analysis scores them both ways.

**AETHER holds out whole regimes.** Severity, assets, noise, deliverability, onset time, and compressor conditions are varied outside the training ranges. Seeds and parameter sets never repeat across splits. Fault truth is written to separate files that inference code can't import.

**All methods share one operating point.** Each threshold is set on validation data against a false-alarm budget and a time-in-alarm limit. An episode counts once, and an event is detected only when an episode starts inside it.

**Selection favors simplicity.** Among methods within budget, the one with the best event skill wins, along with any method whose interval includes it, and the simplest of those is chosen.

**Batch and streaming share code.** One feature function and one alarm rule serve both, and tests check that they give the same answers.

## Revision before either holdout was read

Development results exposed two flaws in version 1:

1. Taking the lowest threshold within budget could choose an alarm that never turns off, because one endless episode is one false alarm. Thresholds are now walked down from the top, stopping at the first violation, with a separate limit on time in alarm.
2. Events lasting days catch unrelated false alarms by chance, which inflated event recall. Each result now reports chance-level recall, and selection uses recall above chance, called event skill.

Version 2 was committed before either holdout was opened. The version 1 development numbers are superseded and aren't cited.

## Revision after technical review

Review found three defects after both holdouts had been read. Version 3 fixes them, and every result was regenerated. **The regenerated holdout results therefore don't come from an unread holdout.**

1. An event ended at the last scored row instead of the last event-labeled row, contrary to the matching rule. No event in the current data is followed by normal rows, so no number changed, and a test now covers the case.
2. Logistic regression stopped at its 500-iteration limit in four of six fits. The limit is now 5,000, all fits converge within 640 iterations, and reaching the limit is an error. Classifier scores now come from decision values, because the log of `predict_proba` still gave minus infinity.
3. The threshold search stopped at the median. It now covers the whole score range.

These fixes changed the AETHER selection: three methods are now statistically tied there, and the rule picks the simplest, static limits. Every experiment stage now runs through `pipelines/experiments/run_stage.py`, which keeps each attempt, including failures, with result hashes before and after.

## Consequences

- 3W classes with few wells can't support credible per-class numbers, and they're reported as unsupported.
- AETHER results measure the detectors against one fictional model. They say nothing about a real gas field.
- Detection delay on AETHER is simulation time from a quasi-steady model, not physical latency.
