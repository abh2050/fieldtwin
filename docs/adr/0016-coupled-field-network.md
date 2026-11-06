# ADR 0016: Coupled network in well-flow form, with connectivity as a typed graph

**Status:** Accepted and implemented in Gate 4.

## Context

The field needs a shared manifold and trunk. Independent well simulators would each assume their own backpressure, so their shared pressures would disagree. Connectivity also has to stay apart from evidence and identity relationships.

## Decision

**Typed directed graph.** `physical_nodes` and `physical_edges` hold physical connectivity, with allowed connections enforced in both Python and the database. Nodes reference only fictional assets. `asset_relationships` keeps facility-level statements, and a test checks that they agree with the graph.

**One coupled solve per state.** The unknowns are well flows. Pipe flows are sums of well flows, so junction balance is exact by construction, and every well sees one value at each shared node.

**A pressure-based solver was tried first and replaced.** It solved squared pressures at junctions, using a convex energy, and it passed all six scenarios. Property tests over arbitrary states then found it failing to converge, because the pipe law `q = sqrt(D / K)` has an infinite slope at zero drop. In the flow form, every term is smooth. Newton iterations fell from about 21 to 4, and residuals to about 1e-15. Five of six output hashes were unchanged. The restriction scenario's changed, because the old solver stopped at a looser tolerance there.

**Compressors are a boundary.** Suction holds setpoint until capacity runs out, then floats. This is enough to make a compressor problem reach every well, and it isn't a compressor map.

**Faults stay separate.** Telemetry is computed after the solve, and each scenario declares one category.

**Local coordinates only.** Assets have local metres from a fictional origin, and `assets.geometry` stays empty. A latitude and longitude would point at a real place, which could imply a real facility. Any map in Gate 8 needs its own decision.

## Consequences

- The network has to remain a tree. Looped gathering would need the pressure form or a loop-flow form, with its singular slopes handled.
- Quasi-steady results appear in one sample, so the data can't support analysis of detection timing against transients.
- Effects and their directions are checked against the topology, which verifies internal consistency, not physical truth.
- This doesn't make the model a validated engineering simulator.
