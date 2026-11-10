# FieldTwin agent guide

`docs/specification.md` is the full specification. `AGENTS.md` holds the rules every agent follows, so read it first.

## Commands

```bash
make bootstrap && make test    # offline suite; network access fails a test
make lint
make acquire                   # real downloads; reuses completed batches
make profile && make validate
uv run pytest -m live -o addopts=''       # real endpoints
uv run pytest -m acquired -o addopts=''   # needs acquired data
make db-reset db-migrate db-seed db-load  # local PostGIS on port 55432
make test-db                              # database tests on CI fixtures
make typecheck
bash scripts/ci_local.sh                  # every CI command in a clean copy
bash scripts/gate3_evidence.sh            # rebuild from nothing and record evidence
make scenario reconcile gate3-reports     # simulator, reconciliation, and generated reports
make field field-reports                  # all six field scenarios and their reports
make gate5-development gate5-holdout gate5-reports  # detection experiments; development before holdout
bash scripts/gate5_evidence.sh            # the Gate 5 rebuild, with evidence
make gate6 inspection-load                # aerial sources, association, evidence pages, reports
make inspection-review                    # list chips awaiting human review
bash scripts/gate6_evidence.sh            # the Gate 6 rebuild, with evidence
make gate7 decision-load decision-reports  # decisions, work orders, modeled economics, reports
make decision-list                        # simulated work orders; record a person's decision with pipelines.decision.decide
bash scripts/gate7_evidence.sh            # the latest full rebuild, with evidence
```

## Cost

Keep model spend at zero for one-time content: write it in the session rather than in scripts that call a paid API. Do not create AWS resources without explicit approval.
