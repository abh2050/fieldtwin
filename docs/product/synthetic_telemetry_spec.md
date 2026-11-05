# Synthetic telemetry specification

**Scope:** the bounded prototype behind AETHER-FAULT-001, for one fictional well and one gathering segment. Implementation: [`packages/scenario_engine/`](../../packages/scenario_engine/). Configuration: [`config/scenarios/aether_fault_001.yaml`](../../config/scenarios/aether_fault_001.yaml). Results: [`reports/scenarios/aether_fault_001.md`](../../reports/scenarios/aether_fault_001.md).

> Everything this model produces is `SYNTHETIC`. It describes a fictional well, and it is not calibrated to, measured at, or representative of any real well.

## Purpose

Give AETHER Field telemetry whose variables stay physically consistent with each other, so later gates can be exercised without borrowing another physical system's data. The model exists to make signals coherent. It doesn't predict how a real pipeline behaves.

## Physical model

A well and a gathering segment in series, in steady state at each sample. All pressures in the equations are absolute pascals.

```text
p_shut_in  --[ well inflow ]-->  p_wellhead  --[ gathering segment ]-->  p_downstream (fixed)
```

**Well inflow** is a back-pressure deliverability curve at the wellhead:

```text
q = C (p_shut_in^2 - p_wellhead^2)^n
```

**Gathering segment** is the isothermal compressible pipe equation, with no elevation or acceleration terms:

```text
p_wellhead^2 - p_downstream^2 = K(s) m^2
m = rho_std q
K(s) = 16 f Z R T / (pi^2 D^5) * [ (L - L_r) + L_r / (1 - s)^5 ]
```

**Restriction severity** `s` is the fractional loss of hydraulic diameter over a restricted length `L_r`. Resistance scales with `D^-5`, so the response is small at first and grows quickly.

**Conservation:** both elements carry the same `q`, so mass is conserved by construction. The solver bisects the balance equation, which is monotonic in `q`, and the invariants confirm the result independently.

## Assumptions

| Assumption | Consequence |
|---|---|
| Quasi-steady: the restriction grows far more slowly than flow adjusts | No line-pack or transient behavior |
| Single-phase gas | No liquids, hydrates, or slugging |
| Isothermal, constant `Z`, constant `f` | Friction doesn't vary with Reynolds number |
| Fixed downstream pressure | Other wells and compressors don't interact, until Gate 4 |
| Fixed shut-in pressure | No reservoir depletion over the simulated week |
| Production choke fully open, with no pressure drop | The wellhead sensor reads the segment inlet pressure |
| No elevation change | No hydrostatic term |
| Linear severity ramp | A scenario input, not a deposition model |

## Parameters

Machine-readable values are in the configuration, which is validated on load. It refuses unknown keys and infeasible values, such as a shut-in pressure at or below downstream pressure. The configuration covers:

- Well and segment geometry, and model parameters.
- Gas properties, and standard conditions (101,325 Pa, 288.15 K).
- Nominal flow and pressure ranges.
- Restriction schedule.
- Sensor placement, units, and noise.
- Sampling interval and random seed.
- Expected physical invariants.

## Units

SI is used internally. Display units are separate, are applied only when presenting values, and never enter the calculation.

| Quantity | Internal | Display |
|---|---|---|
| Pressure | Pa, absolute in the model | psi, with the reference stated |
| Differential pressure | Pa | psi |
| Gas flow | sm3/s at 101,325 Pa and 288.15 K | thousand sm3/d |

## Sensors

| Tag | Asset | Measures | Reference | Noise (1 sigma) |
|---|---|---|---|---|
| `A-03.PT-WH` | A-03 | Wellhead pressure | Gauge | 2,000 Pa |
| `GS-A.PT-DS` | GS-A | Downstream gathering pressure | Gauge | 2,000 Pa |
| `GS-A.DPT` | GS-A | Differential across the segment | Differential | 500 Pa |
| `A-03.FT` | A-03 | Gas flow | Not applicable | 0.0015 sm3/s |

- **Reference frames:** gauge readings subtract a stated ambient pressure through `convert_pressure`, which refuses a conversion without one.
- **Noise:** independent, zero-mean Gaussian, from one seeded stream per sensor. Each sensor has its own noise, so the differential reading isn't computed from the other two readings.
- **Not modeled:** drift, stuck sensors, and dropouts.
- **Flow reading:** clipped at zero, because a meter can't read negative.

## Data separation

Columns starting with `truth_` are simulator ground truth: severity, fault state, and noiseless values. `detector_view()` removes them, and the integration rule refuses to run if it can see them. Gate 5 must use the same separation.

## Invariants

All 12 are declared in the configuration. A run that breaks any of them is refused before it is written or recorded.

| Invariant | Requires |
|---|---|
| `mass_conservation` | Well delivery at the solved pressure equals segment flow |
| `pressure_ordering` | Shut-in above wellhead above downstream, so no reverse flow |
| `inflow_equation_residual` | The inflow equation holds |
| `segment_equation_residual` | The segment equation holds |
| `differential_definition` | Differential equals wellhead minus downstream |
| `positive_flow` | Flow stays above zero |
| `flow_regime_valid` | Mach at most 0.30 and Reynolds at least 4,000 at the narrowest section |
| `severity_bounds_and_monotonic` | Severity is bounded, never falls, and is zero before onset |
| `severity_response_monotonic` | More restriction means less flow and higher upstream pressure |
| `noise_within_bounds` | Each sensor stays within 6 sigma of its truth, after its reference conversion |
| `gauge_reference_consistent` | Gauge sensors read one ambient pressure below absolute |
| `nominal_envelope` | The unrestricted state lies inside the declared operating range |

## Determinism

The same configuration and seed give identical output. `canonical_sha256()` hashes rounded values, so a last-bit floating-point difference between platforms can't change it, and tests compare it with recorded hashes.

## Extending to Gate 4

The prototype is modular, so Gate 4 can extend it. Configuration, physics, sensors, invariants, and events are separate modules, and `solve()` takes arrays of severity. To reach 12 wells, Gate 4 needs a network solver in place of the single series path, because shared segments couple the wells. It should also replace the fixed downstream pressure with a compressor model.

## What this doesn't support

- Conclusions about real wells, pipelines, or restriction behavior.
- Claims about detection performance on real data.
- Any estimate of real production loss or economic impact.
