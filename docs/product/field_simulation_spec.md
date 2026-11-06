# Field simulation specification

**Scope:** a coupled model of the whole fictional AETHER Field. Implementation: [`packages/scenario_engine/`](../../packages/scenario_engine/). Configuration: [`config/facility/aether_network.yaml`](../../config/facility/aether_network.yaml) and [`config/scenarios/aether_field_scenarios.yaml`](../../config/scenarios/aether_field_scenarios.yaml). Results: [`reports/simulation/`](../../reports/simulation/).

> AETHER Field is fictional. Its equipment relationships and telemetry are `SYNTHETIC`, and they must never be represented as real operating data. This is a simplified model. It is not a validated engineering simulator, and no parameter is calibrated.

## Physical network

Pressure is defined at nodes, and equipment that moves gas sits on edges. The graph lives in `physical_nodes` and `physical_edges`, separate from evidence and identity records.

```text
reservoir boundary -> wellhead -> pad header -> shared manifold -> suction header -> compressors -> discharge
   (12 wells)      inflow     flowline     GS-A / GS-B        GS-TRUNK         C-01 to C-04   fixed boundary
```

Maintenance and inspection locations are nodes joined by access routes, which carry no gas. A closed valve or a stopped machine is a run state, so the graph stays fixed. Validation refuses cycles, wrong connection types, nodes without an outflow path or inflow, and pipes shorter than the distance between their ends.

## Equations

All pressures are absolute. Standard flow `q` is in sm3/s.

The network is a tree, so the unknowns are well flows. Each pipe's flow `Q` is the sum of the wells above it, which makes junction mass balance exact by construction. For each flowing well:

```text
(q / C)^(1/n) + sum over its path of K Q^2 + x_suction = p_shut_in^2
K = 16 f Z R T rho_std^2 / (pi^2 D^5) * equivalent length
equivalent length = (L - L_r) + L_r / (1 - s)^5
```

**Compression boundary.** This is a simplified boundary, not a compressor map:

| Regime | When | Suction |
|---|---|---|
| Setpoint controlled | Arrivals are within capacity at setpoint, with recycle taking up the rest | Fixed at setpoint |
| Capacity limited | Arrivals exceed capacity at setpoint | Floats: `p = Q p_ref / capacity` |
| No flow | No well can flow | Setpoint |
| Stopped | Every unit is stopped | Equalizes with connected gas |

Units share flow in proportion to available capacity. Discharge is a fixed boundary, and compression work isn't computed.

## Solver

The well equations are the gradient of a convex function, so the solution is unique, and damped Newton reaches it. A step can remove at most 90% of a well's flow, to stay in forward flow. A well that reaches zero leaves the active set and re-enters if its header falls below its shut-in pressure. Pressures then follow by walking upstream from suction, so every shared node has one value.

Non-convergence raises `SolverDidNotConverge` and returns nothing. Infeasible or unknown states raise `InfeasibleNetworkState`.

**Why flows, not pressures:** the first version solved for pressures and passed all six scenarios, but property tests found it failing in other states, because the pipe law's slope is infinite at zero pressure drop. See [ADR 0016](../adr/0016-coupled-field-network.md).

## Zero-flow states

Nothing flows here, so the equations don't determine a pressure, and these rules set it:

| Situation | Pressure |
|---|---|
| Well shut in | Its wellhead sensor reads its own shut-in pressure |
| Branch with no live source, open to the network | Downstream pressure |
| Closed section with open wells | Highest shut-in pressure among them, because check valves stop gas returning to a reservoir |
| Closed section with no source | Undetermined, reported as `BAD_NOT_MEASURABLE` |
| Open well whose header exceeds its shut-in pressure | Backed out, with zero flow and the header's pressure |

## Validity envelope

A run outside this envelope is refused. Values are in the configuration.

| Limit | Value |
|---|---|
| Mach number at the narrowest flowing section | At most 0.30 |
| Reynolds number when flowing | At least 4,000 |
| Absolute pressure | 0.3 to 8.0 MPa |
| Restriction severity | At most 0.70 |
| Compression ratio | At most 6.0 |

## Assumptions

| Assumption | Consequence |
|---|---|
| Quasi-steady | Effects appear in the same sample. There's no line pack, no transit time, and no transient pressure wave. |
| Single-phase gas, isothermal, constant `Z` and `f` | No liquids, hydrates, or Reynolds-dependent friction |
| No elevation change | No hydrostatic term |
| Constant shut-in pressure | No reservoir depletion |
| Production chokes fully open | No choke control or choke loss |
| Fixed discharge pressure | Nothing downstream of the station is modeled |
| Well parameters are declared, not sampled | Differences between wells are a design choice |

## Scenarios

| Scenario | Category | What changes |
|---|---|---|
| `AETHER-NET-NORMAL` | Normal | Nothing |
| `AETHER-FAULT-001-NET` | Physical | GS-A restriction |
| `AETHER-NET-COMPRESSOR-DERATE` | Physical | C-01 loses capacity |
| `AETHER-NET-SENSOR-DRIFT` | Sensor | Readings only |
| `AETHER-NET-COMM-DROPOUT` | Communication | Readings only |
| `AETHER-NET-PLANNED-SHUTDOWN` | Planned | Valve, compressor, and well state |

A scenario declares one category, and the contract refuses a mix. Telemetry is computed after the solve, so sensor and communication faults can't reach the physics. A drifting sensor keeps reporting `GOOD`, because it doesn't know it's wrong, and only the truth file records the fault.

Gate 3's single-well `AETHER-FAULT-001` stays as a regression reference.

## Determinism

One seed and one parameter set give identical output. Each sensor's noise stream comes from the seed and its tag, so adding a sensor can't change another's noise. Hashes cover values rounded well above solver and platform noise, and CI compares them on Linux x86, Linux ARM, and macOS ARM.

## What this doesn't support

- Conclusions about any real gas system.
- Compressor sizing, pipeline design, or production forecasts.
- Claims about detection performance on real data.
- Transient analysis of any kind.
