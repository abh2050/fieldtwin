# ADR 0014: Domain boundaries and a shared event contract

**Status:** Accepted and implemented in Gate 3. Tightens ADR 0010.

## Context

Gate 2 allowed a conditionally compatible 3W event to be mapped onto AETHER if evidence was supplied for each condition. Gate 3 requires that AETHER and 3W remain separate physical systems, so the assessment shouldn't be able to authorize a mapping at all.

Both domains still need events that later gates can process in one way.

## Decision

**Boundary.** `domain_boundaries` states whether a source can reach a target domain. A trigger on `scenario_mappings` refuses anything without an explicit allowance, so the default is refusal. `petrobras_3w` and `nm_ocd` are both refused for `FICTIONAL_ONSHORE`. No earlier constraint was loosened.

Compatibility classifications stay in place as a record of physical reasoning. They no longer authorize anything on their own.

**Events.** `shared_events` gives both domains one shape, with a `domain` column and constraints that keep them apart:

| | `AETHER_SYNTHETIC` | `OFFSHORE_BENCHMARK` |
|---|---|---|
| Source | `aether_synthetic` | `petrobras_3w` |
| Provenance | `SYNTHETIC` | `DERIVED` for real instances, `SYNTHETIC` for generated ones |
| Must have | Scenario, run, and target asset | Source telemetry event and label |
| Can't have | A source telemetry event | Any AETHER asset, scenario, or run |

**Benchmark adapter.** `pipelines/normalize/petrobras_3w_events.py` converts each 3W instance without changing its records. The onset is the first observation with a non-normal source label. An instance filed under an event class with no such label is flagged as a quality exception.

**Equipment rules.** `equipment_relationship_rules` lists allowed flow connections, and a trigger refuses the rest.

## Consequences

- Sharing a contract doesn't imply transferability. The shape is common, while the physics and evaluation stay separate.
- Two Gate 2 test helpers lift the boundary inside a rolled-back transaction, so the assessment layer can still be tested on its own. Their assertions are unchanged.
- Allowing a future source onto AETHER takes an explicit boundary row and a recorded decision.
