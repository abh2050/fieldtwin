# ADR 0009: Define measurements per equipment class

**Status:** Accepted and implemented in Gate 2.

## Context

A generic `pressure` metric would let an offshore subsea-tree pressure sit beside an onshore wellhead pressure as though they were the same. 3W also doesn't state whether its pressures are absolute, gauge, or differential.

## Decision

- Each `measurement_definitions` row belongs to one equipment class, and no definition is shared between classes.
- `sensor_tag_mappings` carries composite foreign keys to both the tag and the definition, over equipment class, reference type, and units. A mapping across classes, or from an `UNKNOWN` reference to `GAUGE`, can't be stored.
- `UNKNOWN` is an explicit reference type. Every 3W pressure tag uses it and is marked `SEMANTICS_INCOMPLETE`.
- `unit_conversions` requires both units to measure one quantity. A change of pressure reference isn't representable as a unit conversion, because it needs ambient pressure.
- `v_tag_semantics` presents the nine required attributes for each tag.

## Consequences

- 3W tags map only to definitions in their own `OFFSHORE_SUBSEA_WELL` class, which adds little analytical convenience but keeps the meaning honest.
- Crossing domains is possible only through a compatibility assessment and an experimental scenario mapping (ADR 0010).
- AETHER's measurement definitions are design assumptions and describe no data.
