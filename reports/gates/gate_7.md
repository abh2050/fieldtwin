# Gate 7 report: decision support

**Status: implemented and stopped for technical review.** The work is on branch `gate-7` and isn't merged. The final local rebuild from an empty database ran 42 steps, and all passed. Hosted CI is recorded below once it has run.

Date: 2026-11-10. Branch: `gate-7`. Full output of the final local rebuild: [`gate_7_execution_log.txt`](gate_7_execution_log.txt). Decisions: [ADR 0019](../../docs/adr/0019-transparent-decisions-and-modeled-economics.md).

> **Everything here is fictional or modeled.** Recommendations and work orders concern fictional AETHER assets in simulated scenarios. Approvals in the demonstration were made by scripted actors, not people. Economic figures are modeled estimates for a fictional field under declared assumptions, never realized or expected savings. Nothing actuates equipment.

## Headline

- **A synthetic scenario event produced an evidence-backed recommendation and an approved simulated work order.** On AETHER-FAULT-001-NET, the Gate 5 detector alarmed 36 hours after the restriction began. The rules recommended a field inspection of GS-A with priority score 50 (P2), every point explained, and the work order went through creation, approval, and completion. Each transition is recorded with its actor and an audit event.
- **On six scenarios, the engine was right twice, wrong once, and blind once.**
    - Two of three dispatches went to the faulted asset: GS-A for the restriction and C-01 for the compressor derate.
    - The third was a false alarm. A restart transient 45 minutes after a planned shutdown was dispatched, and it scored highest of all.
    - The sensor-drift scenario produced no alarm, so no recommendation.
- **Localization is weak.** Evidence-sensor deviations are small and close together. C-01 ranked second in its own alarm's evidence, and it was chosen by the consequence rule, which rules version 3 added after the alarms had been seen.
- **In the modeled comparison, fixed monthly rounds cost least on average.** The means were $285k a year for fixed rounds against $387k for risk-based dispatch, and risk-based was cheaper in only 32% of replicates. Route optimization saved $24 a year in a field about 4 km across. Fixed rounds stayed cheapest under every one-at-a-time sensitivity change.

## Acceptance

The specification's Gate 7 deliverables are risk prioritization, a transparent rule engine, work-order approval, audit history, and economic comparison. Its acceptance test is that "a complete synthetic scenario event can generate an evidence-backed recommendation and approved simulated work order."

| # | Criterion | Result | Evidence |
|---:|---|---|---|
| 1 | Risk prioritization | **Met** | An integer score from named terms: alarm start, repeats, evidence age, consequence (the share of the field's wells through the asset, from the Gate 4 network), and open inspection requests. Bands P1 to P3. No detector score is used as a probability, and `failure_probability` can only be empty. [Decision engine](../decision/decision_engine.md) |
| 2 | Transparent rule engine | **Met** | Deterministic, versioned rules in `config/decision/gate7_rules.yaml`. Every recommendation stores its terms, inputs, rules, and explanation, and the database refuses a score that isn't the sum of its terms. Planned operations suppress dispatch, degraded evidence goes to an instrumentation check, and missing evidence asks for more. |
| 3 | Work-order approval | **Met, with scripted approvals in the demonstration** | Only the engine creates, and only a maintenance supervisor approves, rejects, or requests evidence. The database enforces the allowed transitions and refuses a status change without its transition and audit event, including from the application role. The demonstration's approvals are `SCRIPTED_DEMO`; a person's decisions go through `pipelines/decision/decide.py` as `HUMAN`, which the tests exercise. |
| 4 | Audit history | **Met** | Append-only `work_order_transitions`, `audit_events`, and `approval_events`. The [evidence audit](../decision/evidence_audit.md) covers use case UC-08 for every recommendation: source records, transformations, scenario mapping, model version, rule output, assumptions, decision, and outcome. |
| 5 | Economic comparison | **Met, as modeled estimates** | Fixed, risk-based, and route-optimized scheduling over 200 simulated years, with common random numbers and one-at-a-time sensitivity. OR-Tools tours match exhaustive search on small sets. [Scheduling comparison](../economics/scheduling_comparison.md) |
| 6 | The acceptance scenario | **Met** | AETHER-FAULT-001-NET: alarm, recommendation `REC-95c3442869b8a273`, work order `WO-d722f58e5e13` on GS-A, approved and completed, graded afterwards as dispatched to the faulted asset. |
| 7 | Earlier gates still pass | **Met** | The rebuild reran Gates 2 to 6 from an empty database. All six field-scenario hashes match their recorded values. 256 database tests and 37 tests on real data passed. |
| 8 | Tests and CI | **Met locally; hosted CI pending** | 619 offline tests passed. 7 live endpoint checks passed. Every CI command passed in a clean copy of the tracked files. |

## What the engine did

| Scenario | Alarms | Action | Target (score, band) | Graded against truth |
|---|---:|---|---|---|
| AETHER-NET-NORMAL | 0 | — | — | No alarm, correctly |
| AETHER-FAULT-001-NET | 1 | Field inspection | GS-A (50, P2) | Faulted asset |
| AETHER-NET-COMPRESSOR-DERATE | 1 | Field inspection | C-01 (40, P2) | Faulted asset |
| AETHER-NET-SENSOR-DRIFT | 0 | — | — | Fault missed |
| AETHER-NET-COMM-DROPOUT | 0 | — | — | No alarm, correctly |
| AETHER-NET-PLANNED-SHUTDOWN | 2 | Suppressed, then field inspection | —, then GS-B (57, P2) | Suppressed correctly, then a false dispatch |

The detector is the Gate 5 selection, replayed through the streaming engine with its bundle checksum verified. Its alarms match Gate 5's reference results on these scenarios. Decision inputs were only what an operator would know; simulator truth was read afterwards, for the last column only.

## Modeled economics

| Strategy | Mean total a year (5th to 95th percentile) | Labor | Deferred production | Days to repair |
|---|---|---:|---:|---:|
| Fixed rounds, every 30 days | $285,201 ($111,939 to $591,115) | $51,949 | $232,643 | 18.8 |
| Risk-based, with 90-day rounds | $386,676 ($88,030 to $988,091) | $23,256 | $363,084 | 30.2 |
| Route-optimized | $386,652 ($88,030 to $988,073) | $23,237 | $363,084 | 30.2 |

Risk-based dispatch saves labor but leaves faults running longer, because the detector catches about half of restrictions and the rounds are three times rarer. Deferred production dominates the cost. The model favours fixed rounds in one respect: a dispatch that finds nothing never produces a second alarm. All assumptions and the sensitivity table are in the [scheduling comparison](../economics/scheduling_comparison.md).

## Rule and assumption versions

Each was committed before the results it governs, with one disclosed exception.

| File | Version | Change | When |
|---|---:|---|---|
| `gate7_rules.yaml` | 1 | Initial rules | Before any alarm or recommendation |
| `gate7_rules.yaml` | 2 | The data-quality rule named sensor statuses the simulator never emits | Before any alarm |
| `gate7_rules.yaml` | 3 | A work order targets the candidate with the largest consequence share | **After the alarms and their evidence were seen**, before any recommendation |
| `economics.yaml` | 2 | Category mapping, localization, delay sampling, and flow source, which version 1 left undefined | Before any economic result |

Version 3 decided the compressor case: the evidence ranked well A-03 first and C-01 second.

## Evidence

| Check | Result |
|---|---|
| Steps in the final rebuild | 42 of 42 passed |
| Decisions in the database | 4 alarms; 3 field-inspection and 1 suppressed recommendation; 3 work orders, each created by `SYSTEM` and approved and completed by `SCRIPTED_DEMO`; 0 transitions without an audit event. Loading a second time added no rows. |
| Offline tests | 619 passed |
| Database tests | 256 passed |
| Tests on real data | 37 passed |
| Live endpoint checks | 7 passed |
| Clean copy of tracked files | Every CI command passed (611 unit and acquisition tests passed and 1 skipped, the NAIP pixel test) |
| Lint, format, types | Ruff and mypy clean |

## Process notes

- **The first rebuild failed 2 of 42 steps**, both caused by one line the formatter would rewrite in `packages/decision_engine/topology.py`. The pre-check that should have caught it was piped through `tail`, which hid its exit code. The line was fixed and the rebuild rerun; the log in this branch is from the second run.
- **Human decisions use the scenario clock.** Simulated work orders run in simulated 2040, so a person's decision is recorded on the scenario clock (`decided_at`) with the real time kept separately (`recorded_at`). The database orders transitions by the scenario clock.

## Limitations

1. Six scenarios with one seed each can't show that the rules are good. They show the workflow, one false dispatch, and one missed fault.
2. Localization rests on three evidence sensors whose deviations are small and close together.
3. The rules have no notion of a restart transient after planned work. Adding one now would be tuning on the scenario it failed.
4. Demonstration approvals are scripted under an approve-all policy. No person has reviewed these work orders.
5. Every economic assumption except the detector's behaviour and the network's flows is declared, not measured, and those two are themselves synthetic.
6. No generative AI is used. The specification allows Bedrock only as an optional explainer, and no AWS resource or paid model was in scope.

## Scope kept out

No application UI (Gate 8), no AWS resources (Gate 9), no paid model calls, no equipment actuation, and no change to Gate 4 or Gate 5 code or results.
