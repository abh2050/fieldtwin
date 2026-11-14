# FieldTwin

FieldTwin is an industrial decision-support platform: asset registry, provenance-aware data integration, anomaly detection, inspection evidence, and human-approved maintenance. It is demonstrated on AETHER Field.

> **AETHER Field is a fictional industrial production environment.** Public industrial datasets have been used for source-grounded experiments, while cross-source asset associations and operational scenarios are explicitly simulated.

These datasets do not describe one facility. Petrobras 3W was not measured at a New Mexico well, and no public record here was measured at AETHER Field. AETHER telemetry is synthetic and comes from a simplified physical model that isn't calibrated to any real well or validated as an engineering simulator. 3W stays a separate offshore benchmark.

## Status

**Complete (Gates 0 to 8 and 10, Diagnostic Milestone D1).** Gate 9, the AWS deployment, was removed from scope ([ADR 0022](docs/adr/0022-no-cloud-deployment.md)); everything runs on one machine.

**What it is:**

- Real data acquisition and a canonical PostgreSQL/PostGIS schema with provenance enforced by the database.
- A coupled simulation of the whole fictional field.
- Anomaly detection evaluated on two tracks.
- Aerial evidence that relates real methane plumes to real registry wells by proximity only.
- A transparent decision engine with human-gated simulated work orders.
- A preregistered physics-based diagnosis milestone.
- A FastAPI and React application over all of it.

**What it found:**

- Detection is weak.
- Alarm-driven dispatch didn't beat fixed rounds in the cost model.
- The diagnosis milestone was NOT MET.

Nothing is field-validated, and every economic figure is a modeled estimate for a fictional facility.

- **See it:** [project page](docs/index.html) · [walkthrough](docs/demos/walkthrough.md) · [evaluation summary](reports/portfolio/evaluation_summary.md) · [technical overview](docs/technical_overview.md)
- **Trust it:** [security review](docs/security_review.md) · [known limitations](docs/limitations.md) · [costs and teardown](reports/portfolio/costs.md) · [hardening roadmap](docs/roadmap.md)
- **Run it:** `bash scripts/run_demo.sh`, then open http://127.0.0.1:8000.

Gate evidence: [0](reports/gates/gate_0.md), [1](reports/gates/gate_1.md), [2](reports/gates/gate_2.md), [3](reports/gates/gate_3.md), [4](reports/gates/gate_4.md), [5](reports/gates/gate_5.md), [6](reports/gates/gate_6.md), [7](reports/gates/gate_7.md), [D1](reports/diagnostics/final_report.md), [8](reports/gates/gate_8.md), and [10](reports/gates/gate_10.md). Topic reports: [decision support](reports/decision/), [modeled economics](reports/economics/), [detection experiments](reports/experiments/), [aerial evidence](reports/inspection/), [field simulation](reports/simulation/), [AETHER-FAULT-001](reports/scenarios/aether_fault_001.md), [canonical schema](reports/data_quality/canonical_schema.md), [production units](reports/data_quality/production_units.md), and [3W compatibility](reports/reconciliation/semantic_compatibility.md).

## Quick start

The one-command demo is `bash scripts/run_demo.sh`; it needs uv, Node 20 or later, and Docker. The steps it runs, one gate at a time:

Requires [uv](https://docs.astral.sh/uv/) and about 7 GB of free disk, because acquisition stops if it would leave under 5 GB free.

```bash
make bootstrap   # create the Python 3.12 environment
make test        # offline test suite
make acquire     # download real public data, about 1.6 GB
make profile     # data quality and cross-checks
make validate    # re-verify raw data against manifests

# Canonical database (Docker, PostGIS on port 55432)
make db-reset db-migrate db-seed db-load
make test-db     # database tests on committed fixtures

# Reconciliation and the synthetic scenario
make benchmark-events scenario reconcile gate3-reports

# The whole fictional field
make field field-reports

# Detection experiments: development first, then the holdout
make gate5-audit gate5-data gate5-development gate5-holdout gate5-reports

# Aerial evidence: Carbon Mapper plumes and NAIP chips near registry wells, proximity only
make gate6 inspection-load
make inspection-review   # chips awaiting blinded human review

# Decision support: recommendations, simulated work orders, modeled economics
make gate7 decision-load decision-reports
make decision-list       # then record a person's decision with pipelines.decision.decide

# The application: demo database without scripted decisions, local tokens, API and web
make app-db app-tokens
make app-api             # then, in another terminal: make app-web, and open http://127.0.0.1:5173
```

`make acquire` reuses a completed batch. `make acquire REFRESH=1` checks upstream for a new version. A first run took about 11 minutes on the development machine, mostly scanning 48 million OCD production rows.

## How data is classified

| Class | Meaning |
|---|---|
| `OBSERVED` | An original source record, tied to its actual source |
| `DERIVED` | Computed from identified records |
| `REPLAYED` | An existing sequence used in an experimental scenario, keeping its original identity |
| `SYNTHETIC` | Generated values, assets, events, or relationships |
| `INFERRED` | A tentative association that needs supporting evidence and a confidence assessment |

3W's simulated and hand-drawn instances are `SYNTHETIC`, since they did not come from a real well.

## Layout

| Path | Contents |
|---|---|
| `config/` | Source definitions and the fictional facility |
| `data_contracts/` | What each source is expected to contain |
| `pipelines/acquire/` | Source adapters and shared download, manifest, and quarantine code |
| `pipelines/profile/` | Quality reports and integrity validation |
| `db/migrations/` | PostgreSQL and PostGIS schema |
| `packages/domain/` | Pydantic contracts and measurement rules |
| `packages/reconciliation/` | Identity, semantic, geospatial, provenance, scenario, and review modules |
| `packages/scenario_engine/` | Synthetic physical model, sensors, invariants, and events |
| `pipelines/normalize/` | Seeds, loaders, canonical validation, and generated reports |
| `pipelines/reconcile/`, `pipelines/synthetic/` | Run the engine and the scenario, and generate their reports |
| `packages/anomaly_detection/`, `pipelines/experiments/` | Gate 5 detectors, evaluation, and the attempt ledger |
| `packages/inspection/`, `pipelines/inspection/` | Gate 6 aerial evidence: association, claim guard, blind review |
| `packages/decision_engine/`, `packages/optimization/`, `pipelines/decision/` | Gate 7 rules, work orders, routing, modeled economics |
| `packages/diagnostics/`, `pipelines/diagnostics/` | D1 inverse diagnosis, freeze guard, and attempt control |
| `apps/api/`, `apps/web/` | The FastAPI API and the React dashboard (Gate 8) |
| `scripts/run_demo.sh`, `scripts/clean_copy_demo.sh` | One-command demo, and its proof from a clean copy |
| `data/manifests/` | Checksums and counts for each batch (tracked) |
| `data/raw`, `data/bronze` | Downloaded and parsed data (not tracked, recreated by `make acquire`) |
| `data/fixtures/` | Committed test data. Its OCD rows are hand-written, not source records. |
| `reports/` | Generated results and gate reports |
| `docs/` | [Specification](docs/specification.md), requirements, ADRs, architecture, and dataset documentation |

## Safety

FieldTwin is a simulation. It never connects to or operates a well, valve, compressor, PLC, or SCADA endpoint.

## Data credits

Petrobras 3W is licensed CC BY 4.0, and its code Apache 2.0. New Mexico OCD data comes from the Oil Conservation Division, which publishes no explicit license. See [the license inventory](docs/datasets/license_inventory.md).
