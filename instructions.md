# FieldTwin instructions

FieldTwin is an industrial decision-support platform. It is demonstrated on AETHER Field, an entirely fictional onshore natural-gas production field.

| Read | For |
|---|---|
| [`docs/specification.md`](docs/specification.md) | The full technical specification |
| [`AGENTS.md`](AGENTS.md) | Rules for contributors and agents |
| [`README.md`](README.md) | Setup and commands |
| [`reports/gates/`](reports/gates/) | Status and evidence for each gate |
| [`docs/adr/`](docs/adr/) | Significant decisions |

Provenance classes are `OBSERVED`, `DERIVED`, `REPLAYED`, `SYNTHETIC`, and `INFERRED`. Treat unknown relationships as unknown, and don't claim a result without executed evidence.

# 22. REPRODUCIBLE DEMONSTRATION

Create one canonical end-to-end scenario.

Scenario name:

**AETHER-FAULT-001 — Progressive Gathering-Line Restriction**

A fictional natural-gas well experiences increasing flow resistance and downstream backpressure caused by a developing restriction in a gathering-line segment. Telemetry is synthetic and comes from a documented simplified physical model. It does not replay Petrobras 3W or any other source.

Expected workflow:

1. Select fictional Well A-03.
2. Initialize its synthetic operating conditions.
3. Produce baseline telemetry.
4. Introduce a progressively increasing restriction.
5. Generate correlated sensor observations.
6. Record the known synthetic fault onset.
7. Emit an anomaly event through the shared event contract.
8. Preserve the simulator parameters and reproducibility seed.
9. Prepare outputs for inspection prioritization and work-order workflows.
10. Generate a maintenance recommendation using transparent rules (Gate 7).
11. Compare the modeled inspection priority with other fictional assets (Gate 7).
12. Require operator approval, create the work order, and record the decision in the audit log (Gate 7).
13. Display modeled operational and economic outcomes, and the full chain of lineage (Gates 7 and 8).

Petrobras 3W remains an independent offshore benchmark. Do not map its events into fictional AETHER assets, and do not claim transfer of model accuracy between the two domains.

The demo must state:

> AETHER Field is a fictional industrial production environment. Its telemetry is synthetic and comes from a simplified physical model that is not calibrated to any real well. Public industrial datasets are used separately, in their own context.

Do not claim that the simulator is a calibrated representation of a real well.
