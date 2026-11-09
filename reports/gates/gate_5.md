# Gate 5 report: anomaly detection, benchmark evaluation, and uncertainty

**Status: CI_STATUS_PLACEHOLDER**

Date: 2026-11-09. Branch: `gate-5`. Full output of the final local rebuild: [`gate_5_execution_log.txt`](gate_5_execution_log.txt).

> **Two evidence classes, never pooled.** Petrobras 3W results are OBSERVED benchmark evidence from recorded offshore oil wells, labeled by their publisher. AETHER results are SYNTHETIC experiments on a fictional, uncalibrated model. Nothing here is field-validated detection performance, and neither track says anything about the other.

## Headline

- **3W, recorded data:** no method showed event detection skill above chance whose 95% interval excludes zero, either on development wells or on the holdout. The method preferred in development, logistic regression, detected 9 of 40 holdout events at 0.005 false alarms per hour. Its skill above chance was 0.15, with an interval of −0.03 to 0.77.
- **AETHER, synthetic:** detection works in-regime. Logistic regression caught 18 of 20 events, with skill 0.60 (0.33 to 0.87). On held-out regimes it fell to 0.22 (0.06 to 0.38), and it missed every case with compressor conditions outside training. Gradient boosting held up best under shift, at 0.32 (0.21 to 0.44).
- **Unseen wells break calibrated thresholds.** Thresholds were set to keep normal time in alarm under 5% on validation wells. On holdout wells, isolation forest was in alarm 33% of normal time, logistic regression 11%, and static limits 8%. The main 3W finding is that models learn which well they're looking at more than what an event looks like.

## Acceptance criteria

| # | Criterion | Result | Evidence |
|---:|---|---|---|
| 1 | 3W labels audited, including the 43 ambiguous class-9 instances | **Met** | All 498 instances graded. The 43 have no event-labeled row, nothing authoritative resolves them, and they're excluded from both sides of every primary metric. [Label audit](../experiments/3w_label_audit.md) |
| 2 | Evaluation splits are leakage-safe | **Met** | Split by well, checked in code and tests. Overlapping instances hold identical rows, and metrics count each well and time once. A random split would have overstated average precision, at 0.95 by instance and 1.00 by row against 0.81 by well. |
| 3 | Baseline and ML methods run on actual data | **Met** | Static limits, rolling deviation, logistic regression, isolation forest, and gradient boosting, on 299 recorded 3W instances and 272 AETHER cases |
| 4 | AETHER includes held-out scenario variations | **Met** | 8 regimes and 112 cases, never used in fitting or threshold setting |
| 5 | Both tracks produce independent reports | **Met** | [3W benchmark](../experiments/3w_benchmark.md) and [AETHER benchmark](../experiments/aether_synthetic_benchmark.md) |
| 6 | False alarms and detection measured with explicit definitions | **Met** | Rules in `config/experiments/gate5_evaluation.yaml`, committed before fitting. Sample-level and event-level metrics are separate. |
| 7 | Inference runs without ground-truth fault state | **Met** | The contracts have no field for truth and refuse extra fields. Inference code imports neither the simulator nor the labels, which a test checks. Batch and streaming scores agree for all 10 models. |
| 8 | Model artifacts and experiments are reproducible | **Met** | A rebuild from an empty experiment folder reproduced all 91 score, artifact, and dataset checksums, and every other recorded value. Seeds, splits, configurations, feature names, parameters, metrics, hardware, and artifact checksums are logged to a local MLflow store. Reproduction is shown on one machine only. |
| 9 | Numerical reliability tests and timeout protections exist | **Met** | 210 of 210 stress runs completed with matching hashes. Nonconvergence, infeasible state, timeout, and crash were each forced and classified correctly. [Reliability stress](../simulation/reliability_stress.md) |
| 10 | Gate 0–4 regression tests pass | **Met** | The final rebuild reran Gates 0 to 4 from an empty database, with 0 failures. That covers 524 offline tests, 228 database tests, 32 real-data tests, and every CI command in a clean copy. Gate 4's six simulation hashes are unchanged. |
| 11 | CI passes on the feature branch | CI_PLACEHOLDER |
| 12 | Limitations and unsupported claims disclosed | **Met** | See [Limitations](#limitations) |

## How the evaluation was protected

1. **Rules before results.** The evaluation rules, splits, and AETHER design were committed at `5f8f4b4`, before any model was fitted. Plausibility limits followed at `ba35bf1`, also before fitting.
2. **Development before holdout.** The development selections were committed at `09930a4`, before either holdout was read.
3. **Methods weren't tuned.** Each method's parameters were fixed in code ahead of time. Thresholds come from validation data only.
4. **One operating point for all.** The budget was 0.05 false alarms per hour and 5% of normal time in alarm, measured on validation data.

### Changes made after seeing development results

These were found on development data before either holdout was opened, and they're recorded in the configuration file and [ADR 0017](../../docs/adr/0017-detection-evaluation-design.md).

| Change | Why |
|---|---|
| Rules version 2: thresholds walked down from the top, with a time-in-alarm limit | Version 1 took the lowest threshold within budget. An alarm that never turns off counts as one false alarm, so it passed. Thresholds came out absurdly low, and alarms were already running at onset in 10 to 16 of 20 AETHER events. |
| Rules version 2: chance-level recall reported, and selection uses skill above chance | Events last hours to days, so unrelated alarms catch them by chance. Version 1's 0.95 recall on AETHER was largely this. |
| Classifier scores use −log P(normal) in place of 1 − P(normal) | On unseen 3W wells, 17% of normal windows scored exactly 1.0, so they couldn't be ranked. The order is unchanged. |
| Gradient boosting drops features with no value in training | A unit test showed it crashed on an all-missing sensor, which happens in 3W. |
| AETHER selection made on the in-regime test | Version 1 didn't name the data for AETHER selection. |

The version 1 development numbers are superseded and aren't cited.

### Holdout attempts that crashed

The first holdout runs crashed in bookkeeping: the 3W run while checksumming a manifest folder for MLflow, and the AETHER run while perturbing a read-only array. Neither had written results. The 3W run printed nothing. The AETHER run printed its 8 regime lines to a log that I didn't read before rerunning. Both were rerun with only those two fixes, so models, thresholds, and scoring were unchanged.

### A data-reading bug found by the evidence run

Simulated and hand-drawn 3W files reuse names across class folders. For example, `DRAWN_00001` exists under both class 1 and class 7: 39 names cover 86 files. The window builder looked files up by name, so for each repeated name it read one file twice and merged two instances into one sequence. A real-data test caught this. No recorded instance was affected, because real names are unique.

The fix reads each file by its path. Rerunning showed every primary development result and every holdout result unchanged. The one changed number is the generated-data training variant, whose development skill fell from 0.18 to 0.02. Its earlier apparent gain came from the misread files.

## 3W results (OBSERVED)

Development: four folds, 159 events. Holdout: 9 wells, 40 events on 6 wells, and 213 hours of normal operation.

| Method | Development skill (95% interval) | Holdout events | Holdout skill (95% interval) | Holdout false alarms per hour | Holdout time in alarm |
|---|---|---:|---|---:|---:|
| Static limits | −0.00 (−0.05 to 0.03) | 1 of 40 | 0.03 (0.00 to 0.18) | 0.000 | 0.079 |
| Rolling deviation | 0.16 (−0.13 to 0.36) | 14 of 40 | −0.05 (−0.32 to 0.78) | 0.047 | 0.027 |
| **Logistic regression** (preferred) | 0.10 (−0.16 to 0.34) | 9 of 40 | 0.15 (−0.03 to 0.77) | 0.005 | 0.108 |
| Isolation forest | −0.10 (−0.32 to 0.21) | 7 of 40 | 0.03 (−0.15 to 0.63) | 0.009 | 0.331 |
| Gradient boosting | −0.05 (−0.17 to 0.07) | 1 of 40 | −0.12 (−0.32 to 0.14) | 0.009 | 0.002 |

- **Selection:** in development, rolling deviation had the highest skill but exceeded the budget, at 0.053 false alarms per hour. Logistic regression and isolation forest were tied, and logistic regression is simpler. This choice has no demonstrated skill behind it.
- **Per class:** every holdout class sits on one or two wells, so no per-class recall is reported.
- **Ambiguous instances:** counting the 43 as events adds 10 holdout events, and logistic regression detects 2 of them. See [robustness](../experiments/robustness.md).
- **Variants:** none of the gradient boosting variants clearly helps. Adding simulated and hand-drawn training data moved development skill from −0.05 to 0.02. Removing level features gave 0.03, and removing missingness features −0.02.

## AETHER results (SYNTHETIC)

In-regime: 20 events. Held-out regimes pooled: 80 events.

| Method | In-regime events | In-regime skill (95% interval) | Held-out events | Held-out skill (95% interval) | Held-out time in alarm |
|---|---:|---|---:|---|---:|
| Static limits | 11 of 20 | 0.33 (0.06 to 0.58) | 25 of 80 | −0.02 (−0.14 to 0.11) | 0.283 |
| Rolling deviation | 15 of 20 | 0.21 (−0.02 to 0.42) | 55 of 80 | 0.22 (0.10 to 0.35) | 0.047 |
| **Logistic regression** (preferred) | 18 of 20 | 0.60 (0.33 to 0.87) | 49 of 80 | 0.22 (0.06 to 0.38) | 0.211 |
| Isolation forest | 11 of 20 | −0.01 (−0.25 to 0.21) | 42 of 80 | −0.02 (−0.15 to 0.11) | 0.060 |
| Gradient boosting | 9 of 20 | 0.45 (0.22 to 0.67) | 31 of 80 | 0.32 (0.21 to 0.44) | 0.010 |

- **Selection:** logistic regression won in-regime, tied with gradient boosting.
- **Under shift:** compressor conditions and deliverability outside training move the whole field's operating point. Methods anchored to training levels then spend much of normal time in alarm: static limits 28% and logistic regression 21%. Logistic regression detected 0 of 10 compressor-regime events. Rolling deviation compares each series with its own past, so it was least affected.
- **Detection delay:** this is simulation time from a quasi-steady model with faults ramping over days. It says nothing about physical pressure waves or real detection latency.
- **Gate 4 scenarios:** the preferred model detected the restriction, the derate, and the sensor drift in the six accepted runs. It raised no alarm in normal operation or the dropout, and one during planned shutdown.

## Inference

The streaming contract takes asset identity, measurement definitions, timestamped readings with quality, and the model's identity and version. It returns everything the directive lists, with provenance `INFERRED` and the input class `OBSERVED` or `SYNTHETIC`.

On one Apple Silicon machine with one thread:
- **Latency:** p95 per window from 0.06 ms (AETHER static limits) to 4.4 ms (3W isolation forest). Most of it is contract validation.
- **Memory:** process peak RSS of 250 to 330 MB, mostly the Python runtime.
- **Artifacts:** from 2 KB (static and rolling) to 3.1 MB (3W isolation forest).

Details: [inference performance](../experiments/inference_performance.md).

## Reliability

Hardening added:
- **Bounded walks:** both graph walks are now bounded, on top of the existing 80-iteration Newton limit and 16-pass active-set limit. Gate 4's six hashes are unchanged.
- **Process guard:** every run happens in a child process with a hard timeout, a stack dump just before it, and JSON progress lines.
- **Separate outcomes:** nonconvergence, infeasible states, envelope refusals, timeouts, and crashes are reported apart.

All 272 AETHER cases and 210 stress runs went through the guard without a failure.

**The Gate 4 hang is not claimed fixed.** Its cause was never found, and it didn't recur in 30 repeats of the work that was running when it happened. A recurrence would now be stopped and leave a stack trace.

## Evidence

The final rebuild ran 39 steps from an empty database and an empty experiment folder, from 22:51 to 23:16 UTC on 2026-11-09. All passed.

| Suite | Passed | Failed |
|---|---:|---:|
| Offline tests | 524 | 0 |
| Database tests on fixtures | 228 | 0 |
| Tests on acquired real data | 32 | 0 |
| CI commands in a clean copy: unit | 517 | 0 |
| CI commands in a clean copy: contract | 7 | 0 |
| CI commands in a clean copy: Postgres integration | 79 | 0 |
| CI commands in a clean copy: provenance | 149 | 0 |

Ruff, the format check, and mypy pass, and canonical validation shows 21 checks with 0 failures. The earlier evidence run failed 2 steps, both described above, and was rerun after the fix.

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

The architecture diagram has a new page, `detection-evaluation`, exported to [`detection_evaluation.png`](../experiments/detection_evaluation.png). Decisions are in [ADR 0017](../../docs/adr/0017-detection-evaluation-design.md).

## Limitations

1. **No field validation.** Nothing here shows how any method would perform on a real field, AETHER's or anyone else's.
2. **No unseen-well claim for 3W.** The evaluation tests on unseen wells and finds no reliable skill. Several classes have only 1 or 2 wells, and normal operation covers only 9 wells.
3. **The 3W data is a subset.** 498 of 2,228 files, chosen by sorted name, which favors lower well numbers and earlier dates.
4. **Intervals are wide.** The holdout has 40 events on 6 wells. Resampling 6 clusters gives intervals that are themselves imprecise.
5. **Chance level is approximate.** It treats false alarms as a Poisson process at the measured rate.
6. **No per-well adaptation.** Thresholds are global. A deployed system would usually calibrate each well, and this design deliberately doesn't credit that.
7. **AETHER is one fictional model.** Its smooth, consistent fault signatures favor linear models. Results show detection of this simulator's behavior only.
8. **AETHER delay is simulation time.** The model is quasi-steady, so it can't establish physical propagation or detection latency.
9. **Rules were revised once.** This was after development results and before either holdout. The reasons are above, and the earlier numbers are superseded.
10. **The ambiguous 3W instances stay unresolved.** The two doctoral theses in the 3W repository were not read.
11. **Latency is one machine.** Measurements come from a single Apple Silicon laptop, not a deployment.

## Scope kept out

No drone image analysis, maintenance optimization, frontend, or AWS deployment. No paid model calls or AWS resources. No 3W event was mapped to an AETHER asset. Gate 5 isn't merged.
