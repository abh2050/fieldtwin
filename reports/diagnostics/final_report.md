# D1 final result: gathering-line restriction diagnosis

**Outcome: NOT MET.** One preregistered in-regime line failed: measurement top-1 gain was 0.008 (interval 0.000 to 0.023), against at least 0.08. Every other in-regime line passed. Three of six held-out regimes also failed lines, though they don't change the outcome label. Nothing was tuned, changed, or rerun after the final cases were generated.

Date: 2026-11-11. Preregistration version 4. Frozen method `fb38a97`, freeze record `5d0b018`, run from a clean `main` at `bda4a9d`. Attempt ledger: [`final/attempts.jsonl`](final/attempts.jsonl). Outcome: [`final/outcome-final_in_regime-score-001-final_held_out-score-001.json`](final/outcome-final_in_regime-score-001-final_held_out-score-001.json).

> Everything here is SYNTHETIC: fictional AETHER Field and its uncalibrated Gate 4 network model. The in-regime cases come from the same model the method inverts (an "inverse crime"), so in-regime scores mainly test the implementation. The held-out regimes are the meaningful test. Nothing here is evidence about a real gathering system.

## Execution

| Attempt | Status | Cases | Refused by simulator | Diagnosis failures |
|---|---|---:|---:|---:|
| `final_in_regime-generate-001` | Completed | 150 | 0 | — |
| `final_held_out-generate-001` | Completed | 240 (6 × 40) | 0 | — |
| `final_in_regime-score-001` | Completed | 150 | — | 0 |
| `final_held_out-score-001` | Completed | 240 | — | 0 |

Each split was generated once and scored once. A first launch command never started Python, because quoting joined each module name to its argument. It left no ledger entry and no file, and the four attempts above followed it.

## In-regime acceptance (150 cases: 128 restriction, 22 no restriction)

Support met: 128 primary cases (minimum 90), 22 no-restriction (minimum 15), and 63 cases with impact at least 0.1% of field flow (minimum 40).

| Line | Value | Rule | Status |
|---|---|---|---|
| Top-1 | 0.992 | ≥ 0.70 | PASS |
| Top-1 beats B1 | difference 0.33 to 0.50 (B1 top-1 0.578) | lower end > 0 | PASS |
| Top-3 | 1.000 | ≥ 0.90 | PASS |
| Specificity | 1.000 | ≥ 0.80 | PASS |
| Miss rate | 0.008 | ≤ 0.10 | PASS |
| Joint success | 0.992 | ≥ 0.55 | PASS |
| Impact within tolerance | 1.000 | ≥ 0.80 | PASS |
| Median relative impact error | 0.004 | ≤ 0.15 | PASS |
| Brier skill against climatology | 0.971 | ≥ 0.50 | PASS |
| Expected calibration error | 0.044 | ≤ 0.10 | PASS |
| 80% coverage, severity / impact | 0.859 / 0.836 | 0.72 to 0.88 | PASS |
| 95% coverage, severity / impact | 0.977 / 0.969 | 0.90 to 0.98 | PASS |
| Measurement entropy reduction | 0.284 | ≥ 0.25 | PASS |
| **Measurement top-1 gain** | **0.008 (0.000 to 0.023)** | **≥ 0.08, lower end > 0** | **FAIL** |
| Measurement against random | 0.019 to 0.076 | lower end > 0 | PASS |

The failed line is the one review expected. Top-1 was already 0.992 before any measurement, so it could rise by at most 0.008, which it did. Measurement entropy reduction, which failed on development data (0.19), passed here (0.28).

Burden, recommended against random: 130 portable DP and 20 shut-in tests against a uniform mix; mean duration 1.13 h against 1.85 h; 13% against 25% production-interrupting. The recommended action also beat a random action of the same type (interval 0.0005 to 0.056).

Per-pipe results (support at least 8): every reported in-regime pipe had top-1 of 1.0, except FL-A-04 at 0.9 (10 cases). FL-A-05 had 7 cases and is INCONCLUSIVE. FL-A-06, FL-B-03, and GS-TRUNK have no in-regime cases, by design.

## Held-out regimes (240 cases, 34 restriction and 6 no-restriction in each)

| Regime | Top-1 (≥ 0.55) | 80% coverage, severity / impact (0.65 to 0.92) | Joint success | Specificity | B1 top-1 | Lines |
|---|---:|---|---:|---:|---:|---|
| Severity high | 1.000 | **0.529 / 0.500** | 1.000 | 1.000 | 1.000 | coverage FAIL |
| Unseen pipes | 0.971 | 0.735 / 0.706 | 0.971 | 1.000 | 0.824 | PASS |
| Noise high | 1.000 | 0.824 / 0.853 | 1.000 | 1.000 | 0.676 | PASS |
| Deliverability outside | 0.971 | 0.824 / 0.853 | 0.971 | 1.000 | 0.324 | PASS |
| Compressor outside | 1.000 | 0.882 / **0.029** | 0.500 | 1.000 | 0.647 | impact coverage FAIL |
| Degraded operations | **0.412** | **0.441 / 0.588** | 0.382 | 1.000 | 0.059 | top-1 and coverage FAIL |
| **Pooled** | **0.892** (204 cases, ≥ 0.60) | | | | | PASS |

The unseen-pipes regime scored a Brier skill of 0.953 against the fixed in-regime climatology, and 0.934 against its own generator frequencies.

What failed, examined after the fact without changing anything:

- **Degraded operations: the method can't localize where it has no data, and doesn't say so.** When the faulted pipe was on the pad whose telemetry was lost before diagnosis, it was ranked first in 3 of 22 cases. When the fault was on the other pad, it was ranked first in 11 of 11 cases. Two cases where the faulted flowline's own well was shut in were both missed. The method drops sensors with no data, but its probabilities and intervals stay confident instead of widening: coverage was 0.44 and 0.59. This is the most important finding.
- **Compressor outside the trained range: localization holds, impact doesn't.** Every faulted pipe was ranked first, but impact was overestimated by a median factor of 1.6 (range 0.18 to 2.7), so impact coverage was 0.03. With a unit offline and the setpoint outside the trained range, the station's response no longer matches the method's assumption that all compressors are available at the measured suction pressure.
- **Severity high: accurate, but overconfident.** The severity mean absolute error was 0.0001, while the median 80% interval was only 0.0005 wide, so the intervals missed the truth about half the time. Accuracy isn't the problem here; the uncertainty is understated at the top of the severity range.

Three regimes passed outright: unseen pipes, high noise, and deliverability outside the training range. The method localized pipes it never saw restricted in development (top-1 0.971), and it ranked no-restriction cases first in every regime.

## What this shows and doesn't

- Inside the model it was built on, inverse diagnosis localizes and sizes restrictions almost perfectly, with calibrated uncertainty. It beats the residual baseline by 33 to 50 points of top-1, and it recommends measurements that are more informative and less burdensome than random ones.
- It does not yet earn the measurement step: when the diagnosis is already certain, no measurement can improve it, and the preregistered gain wasn't reached.
- It is brittle exactly where real fields are hard: missing telemetry, equipment states outside its assumptions, and extreme severities. There its confidence doesn't fall with its accuracy.
- None of this is evidence about a real field. The cases are synthetic, the model is uncalibrated, and in-regime cases share the method's model structure.

## Disclosures

- Before the final run, the preregistration went through versions 1 to 4 and the freeze through three records, every change timed before any final result. See the [D1 specification](../../docs/product/d1_diagnostic_spec.md) and [development report](development_report.md).
- One final held-out case's parameters were built in memory before the final freeze, while checking the degraded-operations fix. No telemetry or truth was produced.
- The degraded-operations timing was set after the first freeze and before any final case.
- Per-case rows are kept in `data/gold/diagnostics/results/`, which isn't committed. Metrics and acceptance lines are in `final/`.
