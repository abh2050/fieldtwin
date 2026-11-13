# apps/web: FieldTwin operations dashboard (Gate 8)

React, TypeScript, Vite, Tailwind, MapLibre, and ECharts. The UI primitives in `src/components/ui` follow the shadcn/ui pattern (copied-in components built on `class-variance-authority` and `tailwind-merge`).

```bash
make app-api   # in one terminal
make app-web   # in another; open http://127.0.0.1:5173 (proxies /api to :8000)
npm --workspace apps/web run test
npm --workspace apps/web run build
```

## Screens

Overview, Field Map, Asset Explorer, Telemetry Lab, Aerial Inspection, Decision Center, Maintenance, Data Lineage, and Experiment Reports (specification section 14).

## Rules it keeps

- **The disclosure is everywhere.** It lives in the layout, so every screen shows it, including error and not-found screens. Assistive technology announces it as a note.
- **No invented values.** Every number comes from an API call, and no screen has a decorative gauge. Unbuilt results show the command that builds them, and nothing appears in their place.
- **Every state is handled.** Loading, empty, error (with its code and request ID), not built, and degraded service. An API outage is shown at the top of every screen, and an error boundary keeps the layout up if one screen fails.
- **Real and fictional data stay apart.** AETHER's network is drawn in local metres with no basemap. Real aerial evidence is drawn on its own map at its real footprints, labelled `REAL PUBLIC RECORD`, and never on the AETHER map. Without WebGL, the Field Map falls back to an SVG schematic of the same network.
- **Actors are labelled.** `SCRIPTED_DEMO` decisions are labelled "not a person". Actions are offered only to the roles that may take them, and the API and database enforce the roles again.
- **Writes are retry-safe.** Each decision carries a fresh `Idempotency-Key`, so a retried click can't act twice.
- **Negative results are shown as prominently as positive ones.** Detection is weak, alarm-driven dispatch lost to fixed rounds in the model, and D1 is NOT MET.

The bearer token is kept in `sessionStorage` for the tab's lifetime. Local tokens come from `make app-tokens`.
