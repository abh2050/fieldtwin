# ADR 0006: Separate tables for real and fictional assets

**Status:** Accepted and implemented in Gate 2.

## Context

The specification described one `assets` table with an `is_fictional` flag. A flag relies on every query filtering correctly, and one missed filter could present a fictional well as real.

## Decision

- `source_assets` holds real entities named by a source: OCD wells and completions, and 3W's anonymized wells. They are always `OBSERVED`.
- `assets` holds facility assets. They are currently all fictional and always `SYNTHETIC`. It keeps `is_fictional` from the specification, tied to `facilities` by a composite key.
- `source_identifiers.canonical_asset_id` references only `source_assets`, so a real identifier can't resolve to a fictional asset.
- `work_orders.asset_id` and `scenario_mappings.target_asset_id` reference only `assets`, so simulated work can't target a real well.
- `asset_observation_links` has one column for each kind of target, and exactly one must be set.

## Consequences

- Foreign keys enforce the separation, with nothing for a query to forget.
- A future real facility would need a deliberate change to `assets`, which is appropriate.
- This departs from the specification's single table, which section 16 of the [specification](../specification.md) permits with a recorded decision.
