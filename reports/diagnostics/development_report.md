# D1 development report

Date: 2026-11-10. Preregistration: [`config/diagnostics/d1_preregistration.yaml`](../../config/diagnostics/d1_preregistration.yaml), version 4. Frozen method: [`config/diagnostics/d1_method.yaml`](../../config/diagnostics/d1_method.yaml).

> **Development and calibration splits only.** Neither final split has been generated. Everything here is SYNTHETIC: fictional AETHER Field and its uncalibrated Gate 4 model. These numbers are what development looked at; they are not the D1 result.

## Method

**M2, calibrated Bayesian inversion of the network model.** Hypotheses are "no restriction" and each of the 15 pipes at severities 0.01 to 0.69 in steps of 0.01. For a case:

1. **Wells are calibrated** from the first 6 hours, assumed healthy. Each well's deliverability multiplier comes from its measured flow and wellhead pressure.
2. **Every hypothesis is solved** with the network model at that operating point, using the suction pressure as measured now. Its predicted sensor averages are compared with the last 2 hours of telemetry.
3. **The likelihood** uses sensor noise estimated from the data, under a temperature of 3. The prior is 0.15 on no restriction, with the rest spread evenly over all 15 pipes and all severities.
4. **Severity and impact intervals** come from a fine severity grid around the leading pipe, mixed with every other hypothesis.
5. **Evidence** for each leading candidate lists the sensors that favour it over its strongest rival, and those that count against it, in standard deviations.
6. **The next measurement** is the valid action, out of 55, with the largest expected reduction in entropy over the 16 hypotheses. It is computed by Monte Carlo over the posterior.

The diagnosis code (`packages/diagnostics/`) can't import the generator, the simulation layer, or truth, and a test enforces this. Truth reaches a diagnosis only as the reading of a requested measurement, through `pipelines/diagnostics/port.py`.

## Methods compared on the development split (300 cases)

| | M2 calibrated (chosen) | M1 nominal wells | B1 residual baseline |
|---|---:|---:|---:|
| Top-1 (255 restriction cases) | 1.000 | 0.604 | 0.643 |
| Top-3 | 1.000 | 0.686 | — |
| Joint success | 1.000 | 0.384 | — |
| Specificity (45 no-restriction cases) | 1.000 | 0.000 | — |
| Severity MAE when the pipe is right | 0.003 | 0.035 | — |
| Impact within tolerance | 1.000 | 0.561 | — |
| Median relative impact error (119 cases with impact ≥ 0.1%) | 0.004 | 0.147 | — |
| Brier skill against climatology | 0.981 | −0.061 | — |
| Expected calibration error | 0.047 | 0.487 | — |
| Coverage, 80% intervals (severity / impact) | 0.90 / 0.89 | 0.02 / 0.02 | — |
| Coverage, 95% intervals | 0.96 / 0.96 | 0.03 / 0.02 | — |

Calibrating the wells is what makes the difference. With nominal wells, deliverability differences of up to ±10% look like restrictions everywhere, and M1 becomes confidently wrong.

## Uncertainty calibration (calibration split, 100 cases)

The first version of M2 used temperature 1 and the coarse severity grid. On calibration cases its 80% intervals covered the truth only 61–65% of the time, and its 95% intervals 81–85%. Adding the fine grid and then a temperature, both chosen on the calibration split only, gave:

| Temperature | 80% coverage (severity / impact) | 95% coverage | Specificity | Calibration error |
|---:|---|---|---:|---:|
| 2 | 0.85 / 0.81 | 0.91 / **0.89** | 0.93 | 0.035 |
| **3 (chosen)** | 0.87 / 0.84 | 0.95 / 0.95 | 1.00 | 0.050 |
| 4 | **0.89 / 0.88** | 0.98 / 0.98 | 1.00 | 0.059 |

The rule was the smallest temperature in {2, 3, 4} that kept every coverage line inside its preregistered band. Only 3 does. No other setting was tuned. On the development split, which was used only as a check after this choice, 80% coverage came out at 0.90 and 0.89, slightly above the 0.88 band edge. That wasn't corrected.

## Measurement recommendation

| | Development | Calibration |
|---|---:|---:|
| Relative entropy reduction (preregistered at least 0.25) | **0.188** | **0.182** |
| Top-1 gain (preregistered at least 0.08) | **0.000** | **0.000** |
| Against a random valid action (interval above zero) | +0.029 (0.017 to 0.043) | +0.027 (0.008 to 0.049) |
| Against a random action of the same type | +0.012 (0.002 to 0.023) | +0.013 (−0.004 to 0.034) |
| Recommended types | 254 portable DP, 43 shut-in, 3 precision gauge | 84, 15, 1 |
| Mean duration, recommended against random | 1.14 h against 1.79 h | 1.15 h against 1.67 h |
| Share interrupting production, recommended against random | 14% against 22% | 15% against 25% |
| Mean deferred gas, recommended against random | 616 against 934 sm³ | 659 against 1,049 sm³ |

## Matters for the freeze review

1. **In-regime success is close to guaranteed by construction.** The cases come from the same network model the method inverts; only well deliverability, sensor noise, and suction pressure vary, and the method estimates all three. This is the "inverse crime", and it means in-regime results test the implementation, not robustness. The held-out regimes are the meaningful test. Their noise, deliverability, compressor operation, shut-ins, dropouts, and unseen pipes were not seen in development, and nothing in the method was tuned toward them.
2. **Two preregistered measurement lines can't be met in-regime, whatever the measurement.** Before any measurement, top-1 is already 1.0 on development and calibration cases, so a top-1 gain of at least 0.08 is impossible. Little uncertainty remains to remove, and relative entropy reduction reaches 0.18–0.19 against 0.25. Under preregistration version 4 the in-regime outcome will therefore be **NOT MET** unless these lines are changed. Any change now would be timed `AFTER_DEVELOPMENT_RESULTS_BEFORE_FREEZE`. I have not changed anything; this is the reviewer's decision.
3. **The development split's 80% coverage sits slightly above the band**, at 0.90 and 0.89 against an upper edge of 0.88, while the calibration split is inside it. The final in-regime split may land either side of the edge.
4. **Held-out code paths were smoke-tested, not evaluated.** No development case has a shut-in or a dropout, so a unit test feeds a development case with a declared shut-in and a pad's telemetry blanked. It checks that the diagnosis completes and stays well formed. Units offline need no special code: the method uses the measured suction pressure.
5. **The healthy-baseline assumption.** The method assumes the first 6 hours are healthy. That holds in every split, where onset is at least 12 hours, but it is an assumption about the data, not something the method checks.

## Process notes

- Per-case rows are kept in `data/gold/diagnostics/results/`, which isn't committed. Metrics are committed here. The three temperature runs were trimmed to their metrics.
- One run of the full offline suite (639 tests) reported 42 seconds of test time but overran a 10-minute command limit. It happened while a CPU-heavy calibration run was going. A clean rerun took 37 seconds end to end. The same gap was seen in Gate 5 and its cause wasn't found.
- After the final runs, one edit suppressed numpy's "mean of empty slice" warning for sensors with no valid sample. No computed value changes.
