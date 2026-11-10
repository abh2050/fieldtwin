# ADR 0020: Reset the product toward model-based restriction diagnosis

**Status:** Accepted. Planning and preregistration only; no D1 case, method, or result exists.

## Context

Gates 0 to 7 completed the original end-to-end experiment, from real data acquisition through detection, aerial evidence, and decision support. The experiment's central bet failed. The selected detector caught about half of restrictions in held-out regimes, localized weakly, and fed a decision policy that cost more than fixed monthly inspection rounds under Gate 7's modeled assumptions. Building an application and a deployment on that pipeline would polish a capability that doesn't yet earn its place.

What a field model can offer that a generic anomaly detector can't is inverse diagnosis. That means explaining observations through the physics, locating and sizing a fault, quantifying the uncertainty, and choosing the measurement that resolves it.

## Decision

1. **New product goal:** given field telemetry, localize a gathering-system restriction, estimate its severity and production impact, and recommend the next diagnostic measurement with quantified uncertainty.
2. **Roadmap:** Gates 0 to 4 are the foundation. Gates 5 to 7 are completed experimental evidence, kept unchanged, negative results included. Gates 8 to 10 (application, AWS deployment, portfolio) are paused. Diagnostic Milestone D1 comes next, before any UI or deployment work.
3. **D1 covers gathering-line restrictions only.** Work orders, approvals, routing, aerial evidence, cloud deployment, and frontend work are excluded.
4. **Preregistration before development.** Generator parameters, seeds, splits, scoring rules, baselines, and acceptance thresholds are frozen in `config/diagnostics/d1_preregistration.yaml` and committed before any case is generated. Development and final cases are separate. Final cases can't be generated until a freeze record for the method is committed. Truth reaches a diagnosis only as the reading of a measurement the method requested. Later changes are versioned and logged with timing and reason.
5. **Existing evidence is preserved.** No Gate 0 to 7 report, result, or configuration is changed by this reset.

## Why preregister this strictly

Gate 5's holdouts were read several times while defects were being fixed, and Gates 5 and 7 both changed rules after seeing some results. Each change was disclosed, but each weakened the evidence. D1's claim, that a model-based diagnosis localizes and sizes restrictions with calibrated uncertainty, is exactly the kind that is easy to fool yourself about. The final cases therefore stay ungenerated until the method is frozen.

## Consequences

- Reusable infrastructure (acquisition, provenance, audit, guarded state, evidence rebuilds, CI) stays and is maintained. Its value no longer depends on the detector.
- D1 may well fail its thresholds. The thresholds were set before any data, and a failure will be reported as NOT MET rather than renegotiated.
- Paused gates resume only by a later decision that cites D1's outcome.
