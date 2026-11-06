# FieldTwin

FieldTwin is an industrial decision-support platform: asset registry, provenance-aware data integration, anomaly detection, inspection evidence, and human-approved maintenance. It is demonstrated on AETHER Field.

> **AETHER Field is a fictional industrial production environment.** Public industrial datasets have been used for source-grounded experiments, while cross-source asset associations and operational scenarios are explicitly simulated.

These datasets do not describe one facility. Petrobras 3W was not measured at a New Mexico well, and no public record here was measured at AETHER Field. AETHER telemetry is synthetic and comes from a simplified physical model that isn't calibrated to any real well or validated as an engineering simulator. 3W stays a separate offshore benchmark.

## Status

Gates 0 to 4 are the only gates worked on so far: real data acquisition, a canonical PostgreSQL schema, a reconciliation engine, and a coupled simulation of the whole fictional field. There is no trained ML model, application UI, or AWS deployment yet.

Results and evidence: [Gate 0](reports/gates/gate_0.md), [Gate 1](reports/gates/gate_1.md), [Gate 2](reports/gates/gate_2.md), [Gate 3](reports/gates/gate_3.md), [Gate 4](reports/gates/gate_4.md), [field simulation](reports/simulation/), [AETHER-FAULT-001](reports/scenarios/aether_fault_001.md), [canonical schema](reports/data_quality/canonical_schema.md), [production units](reports/data_quality/production_units.md), and [3W compatibility](reports/reconciliation/semantic_compatibility.md).

## Quick start

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
| `data/manifests/` | Checksums and counts for each batch (tracked) |
| `data/raw`, `data/bronze` | Downloaded and parsed data (not tracked, recreated by `make acquire`) |
| `data/fixtures/` | Committed test data. Its OCD rows are hand-written, not source records. |
| `reports/` | Generated results and gate reports |
| `docs/` | [Specification](docs/specification.md), requirements, ADRs, architecture, and dataset documentation |

Other directories are placeholders for later gates, and each README says which gate fills it.

## Safety

FieldTwin is a simulation. It never connects to or operates a well, valve, compressor, PLC, or SCADA endpoint.

## Data credits

Petrobras 3W is licensed CC BY 4.0, and its code Apache 2.0. New Mexico OCD data comes from the Oil Conservation Division, which publishes no explicit license. See [the license inventory](docs/datasets/license_inventory.md).
