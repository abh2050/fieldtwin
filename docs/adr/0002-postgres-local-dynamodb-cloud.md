# ADR 0002: PostgreSQL locally, DynamoDB read models in the cloud

**Status:** The PostgreSQL half was implemented in Gate 2 and remains. The cloud half (DynamoDB and S3 read models) is superseded by [ADR 0022](0022-no-cloud-deployment.md) and was never built.

## Context

Development needs relational integrity and spatial queries. A managed relational database running continuously would be a poor fit for an intermittently used demo.

## Decision

Use PostgreSQL 16 with PostGIS locally as the canonical schema. In AWS, publish materialized views to DynamoDB and analytical Parquet to S3. Reach both through explicit repository interfaces.

## Consequences

- Two adapters must be written and tested. SQL does not translate automatically to DynamoDB.
- Access patterns, keys, pagination, conditional writes, and consistency must be designed on purpose.
- Scans are not an acceptable default query path.
- Integrity constraints enforced by Postgres must be re-implemented in application logic for the cloud path.
