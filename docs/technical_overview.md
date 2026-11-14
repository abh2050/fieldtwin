# Technical overview

FieldTwin is a decision-support system for natural-gas gathering operations, demonstrated on **AETHER Field**, a fictional facility of 2 pads, 12 wells, three gathering segments, and a 4-compressor station. Real public data goes in at one end, and an operator's approved work order comes out the other. Every record keeps where it came from. It runs on one machine (ADR 0022).

- **Run it:** `bash scripts/run_demo.sh`, then open http://127.0.0.1:8000. See the [walkthrough](demos/walkthrough.md).
- **Results:** the [evaluation summary](../reports/portfolio/evaluation_summary.md), generated from the committed result files.
- **Diagram:** `docs/architecture.drawio`, page "System architecture (Gate 10)".

## Data flow

```
 Public sources                Canonical store (PostGIS, 16 migrations)        Experiments and decisions         Application
 ───────────────               ─────────────────────────────────────────       ──────────────────────────        ───────────
 NM OCD (FTP, ArcGIS) ──┐      source_* tables  (real, OBSERVED)                Gate 5 detectors (5 methods,      FastAPI (fieldtwin_app role)
 Petrobras 3W (git)  ───┼─►    raw batches → bronze → canonical, with      ┌──► 2 tracks, held-out regimes)  ┌► 9-screen React dashboard
 Carbon Mapper (API) ───┤      provenance class on every row               │    Gate 6 proximity evidence   │   replay, approvals, audit
 NAIP (STAC)         ───┘      assets / scenarios  (fictional, SYNTHETIC) ─┤    Gate 7 rules → work orders ─┘
                               field simulator (coupled network solver) ──┘    D1 inverse diagnosis (NOT MET)
```

## Layers

| Layer | Where | What it does |
|---|---|---|
| Acquisition | `pipelines/acquire/` | Streams the four public sources into immutable raw batches with manifests and SHA-256 checksums. Reuses completed batches and quarantines invalid records. A failure produces a report, never substitute data. |
| Canonical model | `db/migrations/`, `pipelines/normalize/` | PostgreSQL 16 with PostGIS. Real source assets and fictional assets live in separate tables. Every row carries a provenance class (OBSERVED, DERIVED, REPLAYED, SYNTHETIC, INFERRED). Triggers enforce lineage, domain boundaries, and append-only history. |
| Reconciliation | `packages/reconciliation/`, `pipelines/reconcile/` | Entity resolution and semantic checks across sources. Cross-source links are scored, and unknown stays unknown. |
| Field simulator | `packages/scenario_engine/` | A coupled network solver for wells, flowlines, gathering segments, and compressors. Six deterministic scenarios, with hashes checked on three CI platforms. Truth is stored apart from what sensors see. |
| Detection | `packages/anomaly_detection/`, `pipelines/experiments/` | Five methods on two tracks: synthetic AETHER, and real Petrobras 3W split by well. Chance-corrected event metrics, bootstrap intervals, and an attempt ledger for every stage. |
| Aerial evidence | `packages/inspection/`, `pipelines/inspection/` | Real plumes are related to real registered wells by distance, against a footprint-matched null. A claim guard checks every displayed sentence. Review is blind and append-only. |
| Decisions | `packages/decision_engine/`, `packages/optimization/`, `pipelines/decision/` | A deterministic rule engine whose score is a sum of named terms. The work-order state machine is enforced in the database. Modeled economics compare fixed, risk-based, and route-optimized (OR-Tools) maintenance. |
| Diagnosis (D1) | `packages/diagnostics/`, `pipelines/diagnostics/` | Bayesian inversion of the network solver, with expected-information-gain measurement choice. Preregistered, frozen with a checksum guard, and scored once. Outcome: NOT MET. |
| API | `apps/api/` | FastAPI and Pydantic v2. Runs as a least-privilege role, with bearer-token roles, idempotency keys, correlation IDs, and structured errors. Result files are served with their hashes. |
| Web | `apps/web/` | React, TypeScript, Vite, Tailwind, shadcn/ui-pattern components, MapLibre, and ECharts. Every screen shows the disclosure, and loading, empty, error, and degraded states are handled. |

## Design rules that run through every layer

1. **Provenance is enforced in the database, not by convention** (ADRs 0008, 0015). A synthetic observation without a complete chain to its asset, sensor, run, and parameters is refused.
2. **Real and fictional data never mix.** Separate tables, separate maps, and labels on every screen.
3. **The application can't forge evidence.** Its role can't write sources, scenarios, alarms, recommendations, or results. Transitions and approvals are checked by triggers.
4. **People make decisions.** Only the engine creates a work order, and only a supervisor approves. `HUMAN`, `SCRIPTED_DEMO`, and `SYSTEM` are stored and shown.
5. **Nothing is substituted.** A failed acquisition, or a result that hasn't been built, is reported as such.
6. **Evaluation is honest.** Hold-outs are opened once, preregistered where it matters (D1), and negative results are reported as prominently as positive ones.

## Quality gates

| Check | Where |
|---|---|
| Lint, format, and types (ruff, mypy, tsc) | CI `lint-and-types`, `web` |
| Offline unit and contract tests (network access fails a test) | CI `unit`, `contract` |
| Database integration and provenance invariants on real PostGIS | CI `postgres-integration`, `provenance-invariants` |
| Simulator hashes on Linux x86, Linux ARM, and macOS | CI `simulation-reproducibility` |
| pip-audit, npm audit, gitleaks, actionlint | CI `dependency-and-credential-scan`, `web` |
| Every CI command in a clean copy | `scripts/ci_local.sh` |
| Whole-system rebuilds with recorded output | `scripts/gate*_evidence.sh`, logs in `reports/gates/` |
| Demo from a clean checkout | `scripts/clean_copy_demo.sh` |

## Decisions

22 ADRs in `docs/adr/`. The ones that shape the system most:

- 0006: real and fictional assets are kept apart.
- 0008 and 0015: provenance, and the application role.
- 0016: the coupled network.
- 0017: detection evaluation design.
- 0018: aerial evidence as proximity.
- 0019: transparent decisions and modeled economics.
- 0020: the diagnostic reset.
- 0021: resuming the application gates.
- 0022: no cloud deployment.
