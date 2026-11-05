# ADR 0007: Store production at source grain, one row per product

**Status:** Accepted and implemented in Gate 2.

## Context

The specification lists `oil_volume`, `gas_volume`, and `water_volume` on one record. OCD publishes one row per completion, month, and product, and each product row has its own operator code, effective time, amendment flag, and status.

## Decision

`production_records` keeps one row per source row, with `product_kind`, `reported_volume`, and `unit_id`. `v_production_wide` provides the three-column form as a view. A missing product stays `NULL` there, never zero.

Units come from `production_unit_rules`, which is seeded only from verified evidence. A composite foreign key ties each row's product kind to its unit, so a gas volume can't be stored in barrels and an unknown product can't be stored at all. The loader quarantines such a row and records why.

`reporting_period` is the production month. `eff_dte` is stored separately as `source_effective_at`, because it isn't a production date and OCD doesn't define it as a filing date.

The gas unit is named `MCF_15025PSIA_60F` so that its base conditions travel with it.

## Consequences

- Row-level identity and metadata survive, and each row can be traced to its source.
- Pivoted use needs the view.
- Revision history can't be recovered, because an amended C-115 replaces the earlier file at the source.
