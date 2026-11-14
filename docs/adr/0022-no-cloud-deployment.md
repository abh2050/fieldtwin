# ADR 0022: Remove the AWS deployment (Gate 9) from scope

**Status:** Accepted, 2026-11-14. Supersedes ADR 0001 and the cloud half of ADR 0002.

## Context

Gate 9 would have deployed the application to AWS with CDK: CloudFront and S3 for the web app, API Gateway and Lambda for the API, DynamoDB read models, and a managed identity provider. The specification requires explicit approval before any resource exists, and its final delivery criteria include "the AWS deployment has been validated" and "deployment costs and teardown are documented".

The project owner decided on 2026-11-14 to remove the AWS requirement and go straight to Gate 10. The application already runs end to end on one machine (Gate 8). A cloud deployment would add standing cost and an identity provider without changing any result, and the project has no users who need it hosted.

## Decision

1. **Gate 9 is removed.** No AWS (or other cloud) resource is created, planned, or estimated. The placeholder `aws-*` Make targets and scripts, the CDK and IAM policy folders, and the AWS cost plan are deleted. The AWS profile and region settings leave `.env.example`.
2. **The two cloud delivery criteria are replaced by local equivalents:**
   - "The AWS deployment has been validated" becomes **"the local deployment is validated from a clean copy"**: one command builds and starts the application from the committed code and the acquired raw data, and a live smoke test passes against it.
   - "Deployment costs and teardown are documented" becomes **"local costs and teardown are measured and documented"**: compute time, disk, CI minutes, and paid-API spend, with exact teardown commands.
3. **Local authentication stays.** Bearer tokens from `make app-tokens` remain the authentication for state changes. The specification's "authenticated application" is met for local use only; a hosted deployment would need a managed identity provider, which is listed in the production-hardening roadmap rather than built.
4. **ADR 0001 (Lambda over Fargate) and the DynamoDB part of ADR 0002 are superseded.** PostgreSQL with PostGIS remains the only database.

## Consequences

- Gate 10 can't report measured cloud costs, because none exist. It reports measured local costs instead, and states that cloud cost is zero by design, not by measurement of a deployment.
- The architecture diagram's proposed AWS page is replaced by the local runtime that actually exists.
- `CLAUDE.md` and `AGENTS.md` still forbid creating cloud resources. Reopening hosting would need a new ADR.
