# ADR 0001: Host the API on Lambda rather than always-on Fargate

**Status:** Superseded by [ADR 0022](0022-no-cloud-deployment.md) on 2026-11-14. Never implemented: cloud deployment was removed from scope.

## Context

The demo is used intermittently. Fargate charges for allocated compute while tasks run, and an always-on load balancer adds a fixed cost.

## Decision

Run FastAPI on Lambda through Mangum behind an API Gateway HTTP API. Keep Fargate only as an optional, short-lived batch task.

## Consequences

- Idle cost is close to zero.
- Cold starts and Lambda's package size limit apply. ML dependencies must stay small, or the function must use a container image.
- Long replay jobs cannot run inside a request, so cloud replay must be a bounded batch.
