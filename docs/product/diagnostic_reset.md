# FieldTwin diagnostic reset

Date: 2026-11-10. Decision record: [ADR 0020](../adr/0020-diagnostic-reset.md). Specification for the next milestone: [D1](d1_diagnostic_spec.md). Frozen evaluation plan: [`config/diagnostics/d1_preregistration.yaml`](../../config/diagnostics/d1_preregistration.yaml).

## What Gates 0 to 7 established

Gates 0 to 7 completed the original end-to-end experiment. Real public data was acquired with provenance (Gates 0 to 2). Real and fictional assets were reconciled without being confused (Gate 3), and a coupled simulator of the fictional field was built (Gate 4). Anomaly detectors were evaluated on two separate tracks (Gate 5), real aerial evidence was related to real wells by proximity only (Gate 6), and a transparent decision engine fed human-gated work orders and a modeled scheduling comparison (Gate 7). All eight gates are merged into `main`, and their evidence is in `reports/gates/`.

Gate 7 (`439d4b7`) was merged before its hosted CI result was recorded in `reports/gates/gate_7.md`, which still reads "pending". That run has since finished: [all 9 jobs passed](https://github.com/abh2050/fieldtwin/actions/runs/42902918353), including simulation reproducibility on Linux x86, Linux ARM, and macOS ARM. The gate report is left unchanged, because Gate 0 to 7 evidence is preserved as merged.

## The negative result

**The current detector and decision policy do not outperform fixed inspection rounds.**

- **Detection is weak where it matters.** On held-out AETHER regimes, the selected Gate 5 detector caught 9 of 16 restrictions, with a median delay of 25 hours. On recorded Petrobras 3W data, no method showed robust skill above chance.
- **Localization is weak.** On the six Gate 4 scenarios, the alarm evidence pointed at the right asset only when one sensor stood out. In the compressor case the evidence ranked a well first, and the correct target came from a consequence rule added after the alarms were seen. One dispatch was a false alarm after planned work, and the sensor-drift fault raised no alarm.
- **The decision policy loses the modeled comparison.** Under Gate 7's declared assumptions, risk-based dispatch cost $386,676 a year on average, against $285,201 for fixed monthly rounds, and it was cheaper in only 32% of simulated years. Fixed rounds stayed cheapest under every one-at-a-time sensitivity change. Route optimization saved $24 a year.

These are results on a fictional, uncalibrated model under declared assumptions. They don't show that risk-based maintenance can't work. They show that this detector and policy don't earn their place, because the pipeline flags that something is wrong without saying where, how badly, or what to measure next.

## What to keep and what is missing

**Reusable workflow infrastructure.** This is general engineering, valuable and not specific to field twins:

- Acquisition with manifests, checksums, quarantine, and failure reports (Gates 1 and 6).
- The canonical schema and its provenance rules, with real and fictional assets kept apart (Gates 2 and 3).
- Append-only decisions, audit trails, guarded state transitions, and an application role (Gates 3, 6, and 7).
- Evidence rebuilds, attempt records, CI on three platforms, and generated reports (all gates).
- The claim guard and blind-review patterns (Gate 6).

**The differentiated field-twin capability.** This is what a physical model of the field should make possible, and what Gates 5 to 7 didn't deliver:

- **Inverse diagnosis.** Use the network model to explain the observed pressures and flows, rather than scoring how unusual they look.
- **Localization** to a specific pipe, with evidence for and against each candidate.
- **Severity and impact estimation** in physical units: how restricted the pipe is, and how much gas is being lost.
- **Quantified uncertainty** that is calibrated, not merely reported.
- **Measurement planning.** Say which single extra reading would most reduce the uncertainty.

## New product goal

> **Given field telemetry, localize a gathering-system restriction, estimate its severity and production impact, and recommend the next diagnostic measurement with quantified uncertainty.**

## What changes

| Area | Status |
|---|---|
| Gates 0 to 4 | Foundation. Kept and maintained. |
| Gates 5 to 7 | Completed experimental evidence. Kept unchanged as a record, including their negative results. |
| Gates 8 to 10 (application, AWS deployment, portfolio) | **Paused.** No UI, deployment, ticketing, work-order features, or portfolio polish until D1 is evaluated. |
| Diagnostic Milestone D1 | Next. Gathering-line restrictions only. See the [D1 specification](d1_diagnostic_spec.md). |

D1 excludes work-order generation, approvals, routing, aerial evidence, cloud deployment, and frontend work.

## How D1 avoids repeating Gate 5's problems

Gate 5's holdouts were read several times while defects were being fixed, and its rules changed after results were known. D1 freezes its generator, seeds, splits, scoring rules, and acceptance thresholds now, before any case is generated. Final evaluation cases can't be generated until the method is frozen and recorded. Evaluation truth reaches a diagnosis only as the reading of a requested measurement. Any later change is logged with its timing and reason.
