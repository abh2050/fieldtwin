# ADR 0013: Record every reconciliation outcome as an append-only decision

**Status:** Accepted and implemented in Gate 3.

## Context

Reconciliation can quietly turn a guess into a fact, especially when tentative associations and verified relationships share a table or a status. Gate 2's `source_reconciliation_evidence` holds field comparisons but not decisions.

## Decision

`reconciliation_decisions` stores each outcome with its source identifiers, relationship type, method, evidence, optional confidence and uncertainty, verification status, provenance, algorithm version, and timestamp. It is append-only, and a change is a new row that supersedes the old one.

| Rule | Enforced by |
|---|---|
| Identity needs an authoritative identifier, or a reviewer citing one | Check constraints |
| Names, proximity, and unit similarity can't assert identity | Check constraint |
| A real source asset can't be related directly to a fictional asset | Check constraint |
| `INFERRED` can never be `VERIFIED`, so the two are always distinguishable | Check constraint |
| Proximity is an unverified candidate, and a reviewer can only reject it | Check constraint and review code |
| Experimental assignments can't be `VERIFIED` or `OBSERVED` | Check constraint |
| Human decisions link to a review and the decision they supersede | Check constraint |

**Confidence stays NULL for proximity,** because distance isn't a probability, and inventing a number would imply calibration that doesn't exist.

**Modules:** identity, semantic, geospatial, provenance, scenario, and review live in `packages/reconciliation/`, and `pipelines/reconcile/run.py` runs them. Each is safe to re-run for one algorithm version.

**Review:** open decisions wait in `v_reconciliation_review_queue`. Only a named reviewer with a stated rationale changes a status, and no automatic process does.

## Consequences

- Python contracts repeat the key rules for clear errors, while the database stays the final guard.
- Proximity candidates accumulate in the queue until someone reviews them, which is intended.
- A new algorithm version adds rows without replacing older decisions, so consumers should read `v_current_reconciliation_decisions` and filter on version.
