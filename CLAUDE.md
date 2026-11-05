# FieldTwin agent guide

`instructions.md` is the full specification. `AGENTS.md` holds the rules every agent follows, so read it first.

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
bash scripts/gate2_evidence.sh            # rebuild from nothing and record evidence
```

## Cost

Keep model spend at zero for one-time content: write it in the session rather than in scripts that call a paid API. Do not create AWS resources without explicit approval.
