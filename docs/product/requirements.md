# Product requirements

Status shows delivery as of Gate 5. "Planned" means no implementation exists yet.

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
| UC-01 | Asset overview | Show the fictional wells, pads, gathering, and compression assets | 4, 8 | Asset network and simulation implemented; display planned |
| UC-02 | Production context | Show production in its original reporting grain, never lease totals as well output | 2, 8 | Canonical records with verified units; display planned |
| UC-03 | Fault detection | Detect anomalies against the known synthetic onset. Evaluate 3W separately on its own labels. | 5 | Five detectors evaluated on separate 3W and AETHER tracks; display planned. Not field-validated |
| UC-04 | Aerial inspection | Show georeferenced evidence, keeping proximity separate from attribution | 6 | Planned; sources deferred |
| UC-05 | Maintenance prioritization | Use transparent rules and calibrated risk where available | 7 | Planned |
| UC-06 | Human-approved work orders | Approve, reject, or request evidence, enforced on the backend | 7 | Planned |
| UC-07 | Scenario comparison | Compare schedules, labeling all savings as modeled | 7 | Planned |
| UC-08 | Evidence audit | Trace each recommendation to records, transforms, model, decision, and outcome | 7, 8 | Planned; manifests started |

## Cross-cutting requirements

| ID | Requirement | Status |
|---|---|---|
| R-01 | Every record keeps its source identity and provenance class | Implemented through canonical data and enforced by the database |
| R-02 | A failed acquisition produces a failure report and no substitute data | Implemented and tested |
| R-03 | Invalid records are quarantined with a reason | Implemented and tested |
| R-04 | Raw batches are immutable and verifiable by checksum | Implemented and tested |
| R-05 | Every screen discloses that AETHER Field is fictional | Planned; `docs/index.html` already does |
| R-06 | State changes need authentication, server-side roles, and an audit event | Planned |
| R-07 | Nothing can actuate physical equipment | Enforced by design: no such integration exists |
| R-08 | The product stays fully functional without Bedrock | Planned |
| R-09 | Real and fictional assets have separate identities | Implemented and tested |
| R-10 | Offshore measurements can't map to onshore equipment | Implemented and tested |
| R-11 | Tentative associations stay separate from verified relationships | Implemented and tested |
| R-12 | Scenario telemetry obeys declared physical invariants | Implemented and tested for all six field scenarios |
