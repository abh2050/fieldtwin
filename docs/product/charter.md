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
| Cloud | AWS, with profile and region set through configuration, environment `dev` |
| Budget target | At most $150 per month for experimental infrastructure. This is a target, not a measured bill. |
| Deployment | First deployment private and authenticated, and only after explicit approval |
