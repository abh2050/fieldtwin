# Product requirements

Status shows delivery as of the diagnostic reset (2026-11-10, [ADR 0020](../adr/0020-diagnostic-reset.md)). "Planned" means no implementation exists yet; "Paused" means planned work stopped by the reset.

## Product goal

> Given field telemetry, localize a gathering-system restriction, estimate its severity and production impact, and recommend the next diagnostic measurement with quantified uncertainty.

This replaces the original goal of an end-to-end inspection and maintenance product. Why: [diagnostic reset](diagnostic_reset.md).

## Personas

| Persona | Needs |
|---|---|
| Field Operator | Monitor wells and equipment, review abnormalities, request inspections |
| Reliability Engineer | Analyze operating patterns, failure events, and equipment risk |
| Maintenance Supervisor | Approve actions, assign resources, track outcomes |
| Technical Reviewer | Audit model performance, lineage, assumptions, and safety controls |

## Use cases

| ID | Use case | Key requirement | Gate | Status |
|---|---|---|---|---|
| UC-01 | Asset overview | Show the fictional wells, pads, gathering, and compression assets | 4, 8 | Asset network and simulation implemented; display paused |
| UC-02 | Production context | Show production in its original reporting grain, never lease totals as well output | 2, 8 | Canonical records with verified units; display paused |
| UC-03 | Fault detection | Detect anomalies against the known synthetic onset. Evaluate 3W separately on its own labels. | 5 | Completed experimental evidence: five detectors on separate tracks. 3W shows no robust skill; AETHER held-out restriction recall 9 of 16. Not field-validated |
| UC-04 | Aerial inspection | Show georeferenced evidence, keeping proximity separate from attribution | 6 | Completed experimental evidence: proximity and coverage only, blind review enforced; no reviews recorded. Display paused |
| UC-05 | Maintenance prioritization | Use transparent rules and calibrated risk where available | 7 | Completed experimental evidence: explained rules on six scenarios, 2 of 3 dispatches correct. Further work paused |
| UC-06 | Human-approved work orders | Approve, reject, or request evidence, enforced on the backend | 7 | Implemented and enforced in the database; demonstration approvals scripted. Further features paused |
| UC-07 | Scenario comparison | Compare schedules, labeling all savings as modeled | 7 | Completed experimental evidence: fixed rounds cheapest under the modeled assumptions |
| UC-08 | Evidence audit | Trace each recommendation to records, transforms, model, decision, and outcome | 7, 8 | Implemented for Gate 7 recommendations; display paused |

## Diagnostic requirements (Milestone D1)

Gathering-line restrictions only, on fictional AETHER Field. Specification: [D1](d1_diagnostic_spec.md). Frozen evaluation plan: [`config/diagnostics/d1_preregistration.yaml`](../../config/diagnostics/d1_preregistration.yaml), version 4.

| ID | Requirement | Status |
|---|---|---|
| D1-01 | Rank all 15 pipes and "no restriction" by probability | Preregistered |
| D1-02 | Explain the evidence for and against each leading candidate, sized against sensor noise | Preregistered |
| D1-03 | Estimate restriction severity with central 80% and 95% intervals | Preregistered |
| D1-04 | Estimate production impact in sm³/s with central 80% and 95% intervals | Preregistered |
| D1-05 | Quantify uncertainty so that probabilities and intervals are calibrated, and probabilities beat the generator-matched climatology | Preregistered |
| D1-06 | Recommend the next measurement action (type and target) expected to reduce localization uncertainty the most, report its duration and operational burden, and update after its reading | Preregistered |
| D1-07 | Read only operator-visible inputs. Truth reaches a diagnosis only as a requested measurement's reading | Preregistered |
| D1-08 | Final evaluation cases stay ungenerated until the method is frozen, and are scored once | Preregistered |
| D1-09 | Succeed jointly: the right pipe, severity, and impact in the same case | Preregistered |
| D1-10 | Report a result as INCONCLUSIVE when its case count is below the frozen minimum, never as met | Preregistered |

Excluded from D1: work-order generation, approvals, routing, aerial evidence, cloud deployment, and frontend work.

## Roadmap

| Stage | Scope | Status |
|---|---|---|
| Gates 0 to 4 | Foundation: acquisition, canonical model, reconciliation, field simulator | Complete. Kept and maintained |
| Gates 5 to 7 | Detection, aerial evidence, decision support | Complete. Kept unchanged as experimental evidence, including negative results |
| **D1** | **Gathering-line restriction diagnosis** | **Evaluated 2026-11-11: NOT MET** ([final report](../../reports/diagnostics/final_report.md)) |
| Gate 8 | Application | Resumed 2026-11-12 ([ADR 0021](../adr/0021-resume-application-gates.md)) |
| Gate 9 | AWS deployment | Resumed; needs explicit approval before any AWS resource |
| Gate 10 | Portfolio demonstration | Resumed |

ADR 0021 resumed Gates 8 to 10 after D1 concluded NOT MET. No further research milestones are planned.

## Cross-cutting requirements

| ID | Requirement | Status |
|---|---|---|
| R-01 | Every record keeps its source identity and provenance class | Implemented through canonical data and enforced by the database |
| R-02 | A failed acquisition produces a failure report and no substitute data | Implemented and tested |
| R-03 | Invalid records are quarantined with a reason | Implemented and tested |
| R-04 | Raw batches are immutable and verifiable by checksum | Implemented and tested |
| R-05 | Every screen discloses that AETHER Field is fictional | Implemented in the Gate 8 layout and tested on every route; `docs/index.html` also does |
| R-06 | State changes need authentication, server-side roles, and an audit event | Implemented in the Gate 8 API with local bearer tokens; the database enforces roles and audit again. Gate 9 replaces local tokens with a managed identity provider |
| R-07 | Nothing can actuate physical equipment | Enforced by design: no such integration exists |
| R-08 | The product stays fully functional without Bedrock | Planned |
| R-09 | Real and fictional assets have separate identities | Implemented and tested |
| R-10 | Offshore measurements can't map to onshore equipment | Implemented and tested |
| R-11 | Tentative associations stay separate from verified relationships | Implemented and tested |
| R-12 | Scenario telemetry obeys declared physical invariants | Implemented and tested for all six field scenarios |
