# Gate 0 report: project foundation

**Status: PASSED** on 2026-11-05.

**Acceptance criterion:** a clean checkout successfully initializes the environment.

## Evidence

No commit exists yet, so the check copied exactly the files Git would track (`git ls-files -co --exclude-standard`) into an empty directory and ran from there.

| Step | Result |
|---|---|
| `make bootstrap` | Environment created from `uv.lock`, Python 3.12 |
| `make test` | 79 passed, 10 deselected (live and acquired-data tests) |
| Raw or bronze data in the copy | 0 Parquet files outside `data/fixtures/` |
| `make aws-plan`, `make aws-deploy` | Exit non-zero and do nothing, as intended before Gate 9 |
| `docker compose config` | Valid. The database container was not started, as it is first needed in Gate 2. |
| `ruff check .` | No findings |
| `docs/architecture.drawio` | Well-formed XML (`xmllint`). Not opened in the draw.io application. |

## Delivered

| Deliverable | Location |
|---|---|
| Repository scaffold | Pre-existing scaffold kept and filled in; changes in [ADR 0005](../../docs/adr/0005-scaffold-changes.md) |
| Product requirements | [Charter](../../docs/product/charter.md), [requirements](../../docs/product/requirements.md) |
| Architecture decisions | [`docs/adr/`](../../docs/adr/), 5 records |
| AWS cost and security plan | [`infra/cost/cost_and_security_plan.md`](../../infra/cost/cost_and_security_plan.md) |
| Initial architecture | [`docs/architecture.drawio`](../../docs/architecture.drawio), logical and AWS pages |
| Developer instructions | [`README.md`](../../README.md), [`AGENTS.md`](../../AGENTS.md), [`CLAUDE.md`](../../CLAUDE.md) |
| Local bootstrap | [`scripts/bootstrap.sh`](../../scripts/bootstrap.sh), `Makefile` |
| Fictional facility definition | [`config/facility/aether_field.yaml`](../../config/facility/aether_field.yaml) |

## Limits

- Only the initial logical and AWS diagrams exist. The other diagrams required at final delivery are due by Gate 10.
- The cost plan has no dollar estimate. Gate 9 must produce one from current prices. No AWS API was called.
- No GitHub Actions workflow exists yet, and `.github/workflows/` is empty.
