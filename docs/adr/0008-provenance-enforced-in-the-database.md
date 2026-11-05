# ADR 0008: Enforce provenance in the database

**Status:** Accepted and implemented in Gate 2.

## Context

Provenance must be a property of records and transformations, not merely a frontend label. Application checks alone can be bypassed by a new loader or a manual update.

## Decision

- `provenance_class` is a PostgreSQL enumeration.
- `transformations` declares each process's inputs, its output class, and whether it alters values. Check constraints refuse an `OBSERVED` output from altered or non-observed input, and a `DERIVED` output from synthetic input.
- Canonical rows reference `(transformation_id, provenance_class)` with a composite foreign key, so a row can't claim a class its process doesn't produce.
- Per-table checks fix the class where only one is valid: `source_assets` and `production_records` are `OBSERVED`, and `assets` is `SYNTHETIC`.
- `scenario_mappings` allows only `REPLAYED` or `SYNTHETIC`, and it is immutable. A new version is a new row.
- A trigger refuses a mapping unless a compatibility assessment for that event class and target class allows it, with evidence for each condition.
- A replayed observation must reference its original observation and a scenario.
- `relationship_type` can't be updated, so `EMISSION_NEAR` can't be promoted to `SOURCE_ATTRIBUTED_TO`.
- Pydantic contracts repeat the most important rules, so errors surface early with clearer messages.

## Consequences

- The tests in `tests/provenance/test_database_invariants.py` attempt each violation against a real database.
- Triggers carry logic that the cloud path must reimplement, since DynamoDB can't express it (ADR 0002).
- A superuser could still disable these controls. ADR 0015 adds the least-privilege role an application must use.
