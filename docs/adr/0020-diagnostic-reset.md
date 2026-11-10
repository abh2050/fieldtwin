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

## Change log

| Preregistration version | Date | Timing | Change and reason |
|---:|---|---|---|
| 1 | 2026-11-10 | Before any case, method, or result | Initial preregistration. |
| 2 | 2026-11-10 | `BEFORE_DEVELOPMENT_RESULTS` | Technical review found four gaps. A uniform 16-way Brier baseline was too easy to beat given the generator's frequencies, so it was replaced with a generator-matched climatology. The random-measurement comparator was ambiguous about targets, so it now samples from 55 enumerated valid actions, with duration and burden reported separately. Severity error ignored mislocalized cases, so a joint success rate became an acceptance line. The material-impact filter could leave too few cases, so minimum support was frozen, with INCONCLUSIVE below it. Still no case generated and no method written. |
| 3 | 2026-11-10 | `BEFORE_DEVELOPMENT_RESULTS` | The accepted Gate 4 solver refused a restriction anywhere but the three gathering segments, so the flowline hypotheses (12 of 15) could never be generated. This was found by one solver call while checking solver speed, before any case or method existed. See the physics change below. |
| 4 | 2026-11-10 | `BEFORE_DEVELOPMENT_RESULTS` | A sweep of the nominal model, `scripts/d1_preregistration_sweep.py` (no D1 case generated), showed version 3 couldn't succeed. Flowline restrictions in the development range never reach the 1% material threshold, so only about 7 of 128 restriction cases would be primary against a minimum of 90; the result would be INCONCLUSIVE whatever the method did. Every in-range restriction is still visible to the permanent sensors, at 3.9 or more standard errors. The 0.5% impact floor also let "no loss" pass on flowline cases. Primary cases are now all restrictions, the impact floor falls to 0.05% of field flow, and relative impact error uses cases with at least 0.1% impact, with a minimum of 40. All other thresholds are unchanged. |

## Physics change for D1: flowline restrictions

This changes an accepted Gate 4 physics contract, so it is justified and evidenced here.

- **Change.** `solve_network` accepts a restriction on a flowline as well as a gathering segment. Both use the same restriction law, an equivalent length `(L - l) + l / (1 - s)^5` over the 50 m restricted length. Other edges, such as well inflow and compression, are still refused. A run's truth table gains a severity column for a flowline only when that run restricts it.
- **Why.** D1's hypotheses include every pipe. Without flowlines, D1 would reduce to choosing among three segments that each carry their own differential-pressure sensor, which would test very little.
- **Regression evidence.** All six Gate 4 scenario hashes match `config/scenarios/aether_field_expected_hashes.yaml`. The Gate 3 golden values in `test_physics.py` pass. Five Gate 5 benchmark cases regenerated after the change, including a held-out GS-TRUNK restriction, are identical to the stored files. The offline suite passes (625 tests). New tests check that a flowline restriction acts mainly on its own well, obeys the pipe law, and uses the same law as a segment. A further test checks that runs without flowline restrictions keep the accepted truth columns.

## Consequences

- Reusable infrastructure (acquisition, provenance, audit, guarded state, evidence rebuilds, CI) stays and is maintained. Its value no longer depends on the detector.
- D1 may well fail its thresholds. The thresholds were set before any data, and a failure will be reported as NOT MET rather than renegotiated.
- Paused gates resume only by a later decision that cites D1's outcome.
