# ADR 0019: Transparent rules, human-gated work orders, and modeled economics

**Status:** Accepted and implemented in Gate 7.

## Context

Gate 7 turns detector alarms on the fictional field into maintenance recommendations and work orders, and compares inspection scheduling strategies. The specification asks for a deterministic, explained engine; operator approval with explicit state transitions and audit events; no automatic actuation; no uncalibrated score treated as a failure probability; and economics labelled as modeled estimates.

## Decision

**Decisions use only what an operator would know.** Recommendations start from detector alarms, produced by replaying each scenario's telemetry through the Gate 5 streaming engine with the selected model, which is checksum-verified on load. The other inputs are the planned-operations calendar, open inspection requests, and consequence shares derived from the Gate 4 network graph. `KNOWN_SYNTHETIC_ONSET` events and other simulator truth are never inputs. Truth is read afterwards, only to grade whether a work order went to the faulted asset.

**The score is a sum of named integer terms.** These are an alarm start, repeated starts, evidence age, consequence (the share of the field's wells flowing through the asset), and an open inspection request. Each term records its input and the rule that produced it, and the database refuses a recommendation whose score isn't the sum of its terms. The detector score only gates "an alarm started". The recommendation has a `failure_probability` field that can only be empty.

**Context and data quality change the action, not just the score.** An alarm on assets inside a declared planned operation is recorded and suppressed. An alarm whose evidence sensors had degraded quality goes to an instrumentation check before any field visit. An alarm with no localizable evidence asks for more evidence.

**Work orders are human-gated and enforced in the database.** The engine can only create a work order, in `RECOMMENDED`. Only a maintenance supervisor can approve, reject, or request evidence. Allowed transitions are a fixed list, and history is append-only in `work_order_transitions`. A status change is refused unless its transition and an audit event already exist. The application role can record decisions, but it can't write alarms or recommendations.

**Demonstration approvals are labelled as scripted.** An automated rebuild has no person in it, so scripted actors approve and complete the demonstration's work orders. They follow a fixed approve-all policy that never reads truth. They're recorded as `SCRIPTED_DEMO`, never `HUMAN`, and every report says so. A person's decision goes through `pipelines/decision/decide.py` as `HUMAN`.

**Economics are a declared simulation.** Fixed rounds, risk-based dispatch, and route-optimized dispatch face the same simulated years. Detector behaviour comes from the Gate 5 held-out results, flows come from the Gate 4 network, and everything else is a stated assumption, with one-at-a-time sensitivity. Every OR-Tools tour is checked against exhaustive search on small sets in the tests. Every output is labelled a modeled estimate for a fictional facility.

**No generative AI.** The specification allows Bedrock only as an optional explainer. No AWS resource or paid model is used, and the product is fully functional without one.

## Rule versions and disclosures

- Rules version 2 replaced data-quality statuses the simulator never emits. It was changed before any alarm was produced.
- Rules version 3 made the work-order target the candidate with the largest consequence share. It was written after the six scenarios' alarms and evidence sensors had been seen, but before any recommendation was generated.
- Economics version 2 defined the category mapping, localization, delay sampling, and flow source that version 1 left undefined. It was written before any economic result.

## Consequences

- The demonstration shows the workflow end to end. It doesn't show that the rules are good: on six scenarios one dispatch was a false alarm, scoring highest, and one fault produced no alarm.
- Under the declared assumptions, fixed monthly rounds have the lowest mean cost, and route optimization saves almost nothing in a field this compact. Those are results about this model, not general claims.
- Gate 8 must connect the application through `fieldtwin_app` and present `SCRIPTED_DEMO` decisions as scripted.
