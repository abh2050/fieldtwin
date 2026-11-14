# Project charter

## Purpose

FieldTwin demonstrates how heterogeneous industrial data can support inspection and maintenance decisions without losing track of where each value came from.

The operating environment, AETHER Field, is fictional: 2 well pads, 12 natural-gas wells, a gathering network, and 4 compressors, modeled on Permian Basin operations.

## Problem

Field operators combine well registries, production reports, sensor data, aerial evidence, and maintenance records from separate systems. Those systems use different identifiers, units, and reporting grains. A careless join can yield a confident answer that is physically or legally wrong.

## Scope

Asset registry, data acquisition, canonical modeling, provenance-aware reconciliation, telemetry processing, fault detection, aerial inspection evidence, decision support, human approval, maintenance tracking, and outcome analysis.

## Out of scope

- Operating real equipment, PLCs, SCADA endpoints, or aircraft.
- Claims about real operators' assets, or realized customer savings.
- Kubernetes, SageMaker endpoints, Neptune, OpenSearch, and managed vector databases in the MVP.

## Principles

1. Build on data first. Real acquisition comes before any dashboard.
2. Keep provenance from ingestion through display.
3. Keep decisions deterministic and explainable. Generative AI may explain but holds no authority.
4. Advance only on executed evidence.
5. Keep cost low: local development, and on-demand cloud with full teardown.

## Success

A technical reviewer can run or inspect the product and distinguish measured outcomes from modeled assumptions. Section 23 of the [specification](../specification.md) lists the full delivery criteria.

## Constraints

| Constraint | Value |
|---|---|
| Cloud | None. Cloud deployment was removed from scope on 2026-11-14 ([ADR 0022](../adr/0022-no-cloud-deployment.md)); everything runs locally |
| Budget target | Zero cloud spend and zero paid model calls. Measured local costs are in `reports/portfolio/costs.md` |
| Deployment | Local only: one command from a clean copy, with local bearer-token authentication for state changes |
