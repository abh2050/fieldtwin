# ADR 0012: AETHER-FAULT-001 uses synthetic gathering-line telemetry

**Status:** Accepted and implemented in Gate 3. Replaces the 3W replay in the original section 22.

## Context

The original scenario replayed a Petrobras 3W event against a fictional well. The Gate 2 assessment found nothing directly compatible, so a replay would present offshore oil-well behavior as onshore gas-well behavior.

## Decision

AETHER-FAULT-001 is now a **progressive gathering-line restriction** on fictional Well A-03 and segment GS-A, with telemetry from a simplified physical model ([specification](../product/synthetic_telemetry_spec.md)).

- **Model:** a back-pressure inflow curve in series with the isothermal compressible pipe equation. A restriction reduces hydraulic diameter over a short length, so resistance scales with `D^-5`.
- **Why this model:** it couples wellhead pressure, downstream pressure, differential, and flow through one conserved flow rate, with few parameters. CFD and multiphase reservoir models would add assumptions without adding credibility, since nothing here is calibrated.
- **Cases:** one nominal and one fault, sharing a seed, so readings are identical before onset.
- **Recording:** `scenario_runs` keeps the parameters, seed, checksums, and invariant results, and it is immutable. Series are linked to fictional assets only as `EXPERIMENTAL_SCENARIO_LINK`.
- **Events:** the known onset comes from the schedule and is labeled as declared. A minimal rule reading sensor columns only proves readings can reach the event contract. It isn't the Gate 5 detector.
- **Later workflows:** `PrioritizationInput` defines what later gates receive, with no score and no recommendation.

## Consequences

- The scenario depends on no external dataset, and its outputs are reproducible from configuration.
- Results reflect the model's assumptions. A detector that does well on this data has shown it can find what the model produces, and nothing about real wells.
- Later steps in section 22 remain for Gates 7 and 8.
