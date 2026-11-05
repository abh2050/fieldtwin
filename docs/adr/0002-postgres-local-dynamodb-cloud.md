# ADR 0002: PostgreSQL locally, DynamoDB read models in the cloud

**Status:** Accepted for the MVP. Not yet implemented (Gates 2 and 9).

## Context

Development needs relational integrity and spatial queries. A managed relational database running continuously would be a poor fit for an intermittently used demo.

## Decision

Use PostgreSQL 16 with PostGIS locally as the canonical schema. In AWS, publish materialized views to DynamoDB and analytical Parquet to S3. Reach both through explicit repository interfaces.

## Consequences

- Two adapters must be written and tested. SQL does not translate automatically to DynamoDB.
- Access patterns, keys, pagination, conditional writes, and consistency must be designed on purpose.
- Scans are not an acceptable default query path.
- Integrity constraints enforced by Postgres must be re-implemented in application logic for the cloud path.
