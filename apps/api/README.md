# apps/api: FieldTwin API (Gate 8)

FastAPI over the FieldTwin database and committed result files. Everything it serves describes fictional AETHER Field, or is a real public record labelled as one.

```bash
make app-db       # rebuild the local database for the demo (needs Gates 6 and 7 built)
make app-tokens   # local bearer tokens, one per role, in .env.app (git-ignored)
make app-api      # http://127.0.0.1:8000, OpenAPI at /docs
uv run pytest apps/api/tests                                    # offline
uv run pytest apps/api/tests -m db -o addopts=--strict-markers  # against PostGIS
```

## Rules it keeps

- **Least privilege.** Every request runs as `fieldtwin_app` (ADR 0015) through `SET ROLE`. Reads run in read-only transactions. The role can write only the human workflow: work-order transitions, approvals, audit events, replay cursors, and idempotency records (migration 0016).
- **No fabricated success.** Work-order creation and decisions go through the database's guarded path (migration 0015). A refused transition returns 409 with the database's reason, never a success.
- **Authentication for every state change.** Bearer tokens come from `FIELDTWIN_API_TOKENS` (`actor:ROLE:token`). Only token hashes are kept. Roles are `VIEWER`, `OPERATOR`, and `MAINTENANCE_SUPERVISOR`. Approvals need a supervisor, which the database enforces again. Authentication is checked before a database connection opens. Gate 9 replaces local tokens with a managed identity provider.
- **Idempotency.** On a POST, an `Idempotency-Key` stores the first successful response in the same transaction as the change. A repeat of the same request returns that response with `Idempotent-Replayed: true`. The same key with a different body is refused with 422.
- **Structured errors and correlation.** Every error is `{"error": {code, message, correlation_id, details}}`. `X-Request-ID` is echoed if it's safe to log, and replaced if not. Each request is logged as one JSON line.
- **Pagination and filters.** List endpoints take `limit` (1 to 500) and `offset`, and return `total`.
- **Results as recorded.** Committed result files are served with their path and SHA-256. A missing one returns 404 `RESULT_NOT_BUILT` with the command that builds it. No value is substituted.
- **Telemetry without truth.** A series is served only after the API checks that the file belongs to its run: run ID, parameter hash, and row count. Simulator truth files are never read.
- **Replay generates nothing.** Replay, pause, and reset move a cursor over a run's stored output, and each change is audited.

## Endpoints

These cover specification section 15, plus the screens' supporting reads: `/api/v1/me`, `/overview`, `/network`, `/scenarios/{id}/runs/{run}/tags` and `/telemetry`, `/inspection-evidence/{chip}/chip.png`, `/reports`, `/reports/{slug}`, `/diagnostics/d1`, and `/work-orders/{id}/request-evidence` and `/complete`. `/lineage/{record_id}` takes `kind:id`, for example `observation:12`.

`POST /work-orders` takes `{"recommendation_id": ...}`. The decision engine creates the order (actor `SYSTEM`, as the database requires), and the requesting person is named in the justification and the audit event. Decisions made here are recorded as `HUMAN`.
