# Deployment

FieldTwin deploys to one machine. Cloud deployment was removed from scope on 2026-11-14 ([ADR 0022](../adr/0022-no-cloud-deployment.md)).

| Task | Command |
|---|---|
| Build everything and serve on :8000 | `bash scripts/run_demo.sh` |
| Build only | `bash scripts/run_demo.sh --no-serve` |
| Development servers (API :8000, web :5173 with hot reload) | `make app-api` and `make app-web` |
| Reset the demo database (keeps built data) | `make app-db` |
| New local sign-in tokens | `uv run python scripts/app_tokens.py --new` |
| Prove it builds from a clean checkout | `bash scripts/clean_copy_demo.sh` |
| Stop the database | `make db-down` |
| Teardown | [Costs and teardown](../../reports/portfolio/costs.md#teardown) |

Validation of the local deployment is recorded in the [Gate 10 report](../../reports/gates/gate_10.md). The [hardening roadmap](../roadmap.md) lists what a hosted deployment would need.
