# Costs and teardown

Measured 2026-11-14T14:00:19-08:00 by `scripts/measure_costs.py`; raw values in [`costs.json`](costs.json).

There is no cloud deployment ([ADR 0022](../../docs/adr/0022-no-cloud-deployment.md)), so the cost of FieldTwin is the local machine, CI minutes, and any paid service. Cloud cost is zero because nothing was deployed, not because a deployment was measured.

## Money

| Item | Spend | How it was checked |
|---|---:|---|
| Paid model APIs | $0 | No model or cloud SDK in any dependency manifest or import |
| Cloud resources | $0 | No infrastructure-as-code files (0 found) and no cloud SDK; ADR 0022 |
| CI | $0 | 103 workflow runs, 901 jobs, 560.5 job-minutes; not billed: GitHub-hosted runners are free for public repositories |
| Public data | $0 | NM OCD, Petrobras 3W, Carbon Mapper, and NAIP are free downloads |

## Local compute

Wall-clock time of each recorded rebuild, from its execution log.

| Rebuild | Minutes | Failed steps |
|---|---:|---:|
| [`gate_2_execution_log.txt`](../gates/gate_2_execution_log.txt) | 1.2 | 0 |
| [`gate_3_execution_log.txt`](../gates/gate_3_execution_log.txt) | 1.9 | 0 |
| [`gate_4_execution_log.txt`](../gates/gate_4_execution_log.txt) | 3.5 | 0 |
| [`gate_5_execution_log.txt`](../gates/gate_5_execution_log.txt) | 21.0 | 0 |
| [`gate_6_execution_log.txt`](../gates/gate_6_execution_log.txt) | 5.1 | 0 |
| [`gate_7_execution_log.txt`](../gates/gate_7_execution_log.txt) | 13.8 | 0 |
| [`gate_8_execution_log.txt`](../gates/gate_8_execution_log.txt) | 9.7 | 0 |

**Clean-copy demo:** `scripts/run_demo.sh` built everything from the tracked files alone, downloading the public sources and retraining the detector, in 64.1 minutes. Live smoke test: 28/28 reads returned 200, and no step failed. Committed run records rewritten by the fresh download (manifests, profiles, validation timestamps, timings): 6. Recorded result files changed: 0, classified file by file in the Gate 10 report.

## Disk

| Location | Size |
|---|---:|
| `data/raw` | 2 GB |
| `data/bronze` | 616 KB |
| `data/silver` | 64 KB |
| `data/gold` | 523 MB |
| `.venv` | 764 MB |
| `node_modules` | 280 MB |
| `apps/web/dist` | 3 MB |
| `mlflow.db` | — |
| `docker volume (local PostGIS)` | 185.5MB |

## Teardown

Nothing runs outside this machine, so teardown is local:

```bash
make db-down                      # stop PostGIS, keep its data
docker compose down -v            # delete the local database volume
rm -rf data/bronze data/silver data/gold apps/web/dist .env.app   # derived data and local tokens
rm -rf data/raw/*/                # acquired raw batches (re-downloaded by make acquire)
rm -rf .venv node_modules         # dependencies
```
