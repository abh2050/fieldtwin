# ADR 0023: Explicit browser demo on the existing static host

**Status:** Accepted, 2026-11-14. Narrows ADR 0022 for the owner-provided static deployment only.

## Context

The owner deployed `apps/web` to an existing Vercel project. The React build is reachable, but
`/health` and `/api/v1/overview` return 404 because the local FastAPI/PostGIS system is absent.
The owner selected an interactive browser demo with labeled simulation data and session-only
work-order actions. This is a presentation mode for the existing results, not a new simulator.

## Decision

- Add an explicit `demo` Vite build mode and configure the existing static project to use it.
  Normal development and production builds continue to require the API. Failed requests never
  switch modes or substitute generated data.
- Export only the six existing AETHER network runs through the local application's read-only,
  least-privilege path. Preserve all samples, original units, times, quality flags, configuration
  hashes, and source paths. Store compact, gzip-compressed columnar telemetry with SHA-256 hashes;
  decode it losslessly in the browser. Export fails if required files or API reads fail.
- Keep public-source rows, real well identifiers, aerial imagery, evidence cards, reviews, tokens,
  prior decisions, and audit events out of the bundle. Public aerial evidence is explicitly marked
  as not packaged, rather than represented as an empty acquisition result. Committed aggregate
  evaluation reports retain their original source identities and hashes, including the independent
  offshore 3W benchmark.
- Replay moves a browser cursor over stored synthetic readings. It creates no new measurements,
  runs no detector, and supplies no simulator truth to the recommendation logic.
- A browser-only role selector demonstrates the workflow. It is not authentication or authorization
  for a service. A visitor must click to approve; there is no automatic approval. Demonstration
  transitions are `SCRIPTED_DEMO`, never `HUMAN`, and the engine's creation is `SYSTEM`.
- Browser actions use session storage, require valid workflow transitions, preserve justifications,
  and support idempotency. Reset clears the session. Nothing is persisted to the API or a database.
  Browser controls are demonstration logic, not a security boundary.
- Health says `demo`, never that an API or database is healthy. The interface identifies the mode,
  stored replay, session-only actions, and omitted aerial evidence.
- Create no cloud resources, backend service, managed database, identity provider, or paid API.
  Supporting the owner's existing static host is the sole hosting exception; the full application
  remains local under ADR 0022.

## Consequences

The existing static deployment can demonstrate investigation and work-order review without a
backend. It cannot demonstrate server-enforced permissions, shared state, authenticated approval,
real aerial evidence, or new simulation execution. The local API remains the reference for those
implemented database controls. New simulation parameters require regenerating and re-exporting
runs locally, rather than fabricating new browser results.
