# ADR 0011: Spatial quarantine rules and fixture distribution

**Status:** Accepted and implemented in Gate 2.

## Spatial quarantine

Bad coordinates must leave spatial analytics without losing the original values or valid production.

- `source_assets` keeps `reported_latitude`, `reported_longitude`, and the original row. These never change.
- `geometry` exists only when `spatial_status` is `USABLE`, enforced by a check constraint.
- `v_spatially_usable_source_assets` is the only spatial population.
- A well is quarantined if it lies more than 30 km from the median location of at least 3 peers reporting the same PLSS township. A township is about 9.7 km square, so a real well shouldn't be close to this limit. The rule contains no well IDs.
- A well is `UNRESOLVED_DATUM` if ArcGIS and FTP don't both name the same datum. The datum isn't guessed, even where OCD says it is standardizing on NAD83.
- A quarantined well's production stays loaded, because its volumes aren't in question.

**Threshold correction.** Gate 1 changed the bronze check to allow up to 1% of wells outside the county box after seeing a failure. That allowance is removed. Any well outside the box now fails unless the quarantine rule excludes it, and canonical validation allows zero usable wells outside the box.

## Fixture distribution

OCD publishes no license or redistribution terms. Its data is public, but that doesn't establish permission to redistribute.

- Real OCD samples stay in `data/fixtures_local/`, which is gitignored.
- CI uses hand-written OCD-shaped rows in `data/fixtures/ci_workspace/`, with made-up API numbers and names.
- 3W fixtures are real, truncated records, redistributed under CC BY 4.0 with attribution.
- `data_contracts/sources/generated/` holds types and fill rates for OCD, with no record values.
- Reports describe quality exceptions in general terms and publish only aggregate volumes. Individual wells stay in the local database.

## Consequences

- CI proves parsing and loading against realistic shapes, not against real OCD records. Real-data checks need a local run after `make acquire`.
