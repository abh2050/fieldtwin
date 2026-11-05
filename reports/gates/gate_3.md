# Gate 3 report: provenance-aware reconciliation and experimental scenario contracts

**Status: IMPLEMENTED, awaiting hosted CI on the branch and review.**

Date: 2026-11-05. Branch: `gate-3`. Full output of the final local rebuild: [`gate_3_execution_log.txt`](gate_3_execution_log.txt).

## Acceptance tests

| # | Test | Result | Evidence |
|---:|---|---|---|
| 1 | A real source asset can't silently become fictional | **Met** | Refused in code, contract, and database: `test_real_source_asset_cannot_become_a_fictional_asset`, `test_invalid_decisions_are_refused_by_the_database`, `test_real_identifier_cannot_resolve_to_a_fictional_asset` |
| 2 | Verified and inferred relationships are distinguishable | **Met** | `INFERRED` can't be `VERIFIED` (check constraint), and reviewed decisions carry `HUMAN_REVIEW` and a review link |
| 3 | Proximity doesn't imply identity | **Met** | 711 real candidate pairs produced 0 identities. 5 pairs at zero distance stay separate wells, and a reviewer can't approve one. |
| 4 | Source telemetry keeps native semantics | **Met** | All 31 tags map only within their own equipment class, and all 10 3W pressures stay `UNKNOWN` |
| 5 | Incompatible mappings fail | **Met** | All 56 attempts to map a 3W tag onto an AETHER definition were refused, in Python and in the database |
| 6 | Experimental mappings preserve source identity | **Met** | `scenario_mappings` is immutable with a composite key. Simulator runs keep parameters, seed, and checksums. |
| 7 | AETHER-FAULT-001 uses synthetic onshore telemetry | **Met** | 0 scenario mappings, 0 3W observations linked to AETHER, and all 8 scenario series are `SYNTHETIC` |
| 8 | The simulator is deterministic and meets its invariants | **Met** | All 12 invariants pass on both cases, and repeat runs match the recorded hashes |
| 9 | Gate 0 to 2 tests continue to pass | **Met** | All still run and pass. The few edits are listed below. |
| 10 | New reconciliation and scenario tests execute | **Met** | 237 new tests, all passing |
| 11 | Documentation matches the implementation | **Met** | Reports and schema document are generated, and tests compare them with fresh output |
| 12 | CI passes on the proposed branch | **Pending** | Awaiting the hosted run on this branch |

## Executed results

| Step | Result |
|---|---|
| Migrations on a fresh database | 11 applied, 41 tables |
| Canonical validation against real bronze | 21 of 21 checks passed |
| Provenance audit on real data | 12 rules, 0 violations |
| Offline tests | 276 passed |
| Database tests on fixtures | 166 passed |
| Tests on real data | 22 passed |
| Live endpoint tests | 5 passed |
| Ruff, format, and mypy on 57 files | Passed |
| `pip-audit`, `gitleaks`, `actionlint` | No findings |
| Every CI command in a clean copy | 0 failed, with no raw or bronze data present |

The physics tests use Hypothesis with a fixed seed: 150 generated parameter sets per property, plus a comparison with the exact closed-form answer when `n = 0.5`.

## Reconciliation engine

| Module | Location | Output on real data |
|---|---|---|
| Identity | `packages/reconciliation/identity.py` | 681 wells and 441 completions verified by identifier. 3W to OCD stays unresolved. |
| Semantic | `packages/reconciliation/semantic.py` | 21 verified within class, 10 unresolved, 56 cross-domain attempts rejected |
| Geospatial | `packages/reconciliation/geospatial.py` | 711 unverified candidates |
| Provenance | `packages/reconciliation/provenance.py` | 12-rule audit, 0 violations |
| Scenario | `packages/reconciliation/scenario.py` | 2 declared, never-verified assignments |
| Review | `packages/reconciliation/review.py` | 722 decisions in the queue, and none promoted automatically |

Every one of the 1,923 decisions stores source identifiers, relationship type, method, evidence, verification status, algorithm version, and a timestamp. Confidence is stored only where justified, and it's NULL throughout this batch, because no decision here has a calibrated probability. Reports: [entity resolution](../reconciliation/entity_resolution.md), [semantic validation](../reconciliation/semantic_validation.md), and [geospatial associations](../reconciliation/geospatial_associations.md).

## AETHER-FAULT-001

The scenario is now a progressive gathering-line restriction on fictional Well A-03 ([report](../scenarios/aether_fault_001.md), [specification](../../docs/product/synthetic_telemetry_spec.md), [ADR 0012](../../docs/adr/0012-aether-fault-001-synthetic-restriction.md)). Section 22 is revised identically in `docs/specification.md` and `instructions.md`, and a test keeps them matched.

From the noiseless model at full severity, against the unrestricted state:

| Variable | Start | End | Change |
|---|---:|---:|---:|
| Gas flow | 0.6758 sm3/s | 0.6124 sm3/s | -9.4% |
| Wellhead pressure | 2,171,427 Pa abs | 2,282,936 Pa abs | +5.1% |
| Segment differential | 171,427 Pa | 282,936 Pa | +65.0% |
| Downstream pressure | Fixed by assumption | Fixed by assumption | None |

**These numbers describe the model, not a real well.** They are consequences of chosen parameters, and they aren't calibrated or validated against any measurement.

The nominal case emits no events. The fault case emits the declared onset at day 2.00 and an integration-proof rule event at day 3.19. **That gap isn't a detection-delay result:** it comes from one seed with no evaluation, and the rule exists only to prove sensor readings can reach the event contract.

## 3W independence

All 498 instances were converted to the shared event contract, keeping their identity, labels, and origin. None names an AETHER asset or scenario. The database now refuses every 3W mapping onto AETHER, even for classes assessed as conditionally compatible, and the default for any unlisted source is refusal ([ADR 0014](../../docs/adr/0014-domain-boundaries-and-shared-events.md)). No model accuracy or transfer learning is claimed.

**New finding for Gate 5:** 43 real instances filed under class 9 (`HYDRATE_IN_SERVICE_LINE`) contain only normal and null labels, with no event-labeled observation. They're recorded as quality exceptions, and their labels are unchanged. Gate 5 must decide how to evaluate them, because scoring them as positive events would count something the labels don't mark.

## Public repository cleanup

| Item | Result |
|---|---|
| Developer AWS profile value | Replaced with a placeholder |
| Organization-specific AWS restrictions | Replaced with generic region configuration requirements |
| Conversational notes in `instructions.md` | Removed. It's now a short entry point. |
| Full technical specification | Moved to `docs/specification.md` |
| Individual OCD well example | Replaced with a general description, and generated reports no longer publish it. Details stay in the local database. |
| Hand-written test rows | Moved to a clearly fictional identifier range |
| Raw data and restricted fixtures | Confirmed ignored |
| Credential scan | `gitleaks` found nothing in the tree or in the existing commit history |
| Personal-path scan | None found, enforced by `tests/unit/test_public_repo.py` |

**Git history wasn't rewritten.** Earlier commits on `main` still contain the AWS profile name, the region restriction note, and the one well's API number and coordinate. None is a credential, the well data is a public-record fact, and the directive reserves rewriting for a genuine confidentiality, security, or licensing issue. Removing them from history would need a separate decision.

## Changes to existing tests

Acceptance test 9 requires earlier tests to keep passing, so every edit is listed here. No assertion was weakened to reach a pass.

| Change | Reason |
|---|---|
| Conditional-mapping test helper lifts the new domain boundary inside its rolled-back transaction | Those tests exercise the assessment layer, which the boundary now sits in front of. A new test proves the boundary refuses by default. |
| Tag count changed from 27 to 31, and the `UNKNOWN` pressure check scoped to 3W | Gate 3 adds 4 synthetic sensors, whose references are declared |
| Observation count scoped to 3W, with a new check for 8 synthetic series | Gate 3 adds simulated series |
| Real-data test no longer names one well | Public cleanup. It now asserts exactly one quarantined well. |
| Hand-written API numbers moved to the 9xxxx range | Public cleanup |
| Canonical check "no experimental links" replaced by "no real observation linked to a fictional asset" | Synthetic links now legitimately exist, and the new rule is the invariant that matters |

## Failures during this gate

| Failure | Resolution |
|---|---|
| The domain boundary trigger crashed on an ambiguous column name | A test caught it before any push. Renamed the variable. |
| A reviewer couldn't reject a proximity candidate, because the constraint and the review code disagreed | Allowed a reviewed rejection, while approval stays impossible |
| Repeatability test expected "already run" where the fixture legitimately yields 0 candidates | Corrected the test |
| Evidence log held local paths while tests were scanning it | The log is now scrubbed as it's written |
| First hosted CI run failed `unit`: the scenario report printed a residual near 1e-16, whose last digits differ between ARM and x86. The local clean copy couldn't catch it, since it runs on one CPU. | The report now states a bound for values below 1e-12. The test wasn't loosened, and the simulator hashes matched on both CPUs. |
| The scan test caught this on the first evidence run, with 5 failed steps including lint and types | Fixed each, then rebuilt from nothing |

## Limitations

1. **The simulator is uncalibrated and simplified.** It's single-phase, isothermal, and quasi-steady, with fixed boundary pressures, for one well and one segment. Its consistency checks show it obeys its own equations, not that those equations describe a real pipeline.
2. **Invariant coverage is limited to declared properties.** Passing them doesn't validate parameter choices.
3. **The 711 proximity candidates are unreviewed.** No review has taken place, and the workflow has been tested with test reviewers only.
4. **Emission association has no real data.** The `EMISSION_NEAR` path is tested with hand-written points, because Carbon Mapper is deferred to Gate 6.
5. **OCD agreement isn't independent.** Identity across OCD's two systems shows internal consistency.
6. **Compatibility is still engineering judgment,** and the classifications now serve as a record rather than an authorization.
7. **Real-data checks run locally,** and CI covers fixtures only.
8. **PostGIS runs under emulation locally,** while CI runs it natively.
9. **The prioritization contract is a shape only.** No score, decision, or work order is produced, and Gate 7 owns those.

## Decisions for review

1. **Merge.** Review branch `gate-3`, then decide whether to merge to `main`.
2. **Git history.** Decide whether older commits need any further action. This report recommends leaving them.
3. **Class 9 labels.** Gate 5 needs a rule for the 43 instances without event labels.

Gate 4, 5, and 6 were not started. No AWS calls or paid model calls were made.
