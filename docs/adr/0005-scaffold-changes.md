# ADR 0005: Changes to the specified repository scaffold

**Status:** Accepted and implemented.

The specification allows scaffold changes if they are recorded here.

| Change | Reason |
|---|---|
| Added `pipelines/acquire/common/` | Shared download, manifest, and quarantine code used by every adapter |
| Added `.python-version` and `uv.lock` | Reproducible Python 3.12 environment. The machine's default `python3` is 3.10. |
| Added `pipelines/acquire/cli.py` and `pipelines/profile/` entry points | One command per pipeline stage, called from `make` |
| Set uv `package = false`, with the repo root on `PYTHONPATH` for tests | The layout is an application monorepo, not a published package |
| Added `data/fixtures_local/`, gitignored | Real OCD samples can't be committed (ADR 0011) |
| Added `data_contracts/sources/generated/` | Schemas measured from acquired data, separate from hand-written contracts |
| Added `docs/adr/` entries 0006 to 0011 and `scripts/gate2_evidence.sh`, `scripts/ci_local.sh` | Gate 2 decisions and repeatable evidence |
| Added `docs/specification.md`, with `instructions.md` as a short entry point | Keeps the full technical specification separate from contributor guidance (Gate 3) |
| Added `reports/scenarios/`, and ADRs 0012 to 0014 | Gate 3 scenario results and decisions |
| Added `reports/gates/gate_3_merge_verification.md` | Records the merge conditions, which initially failed |
| Placed quarantine files at `data/bronze/<source>/<batch>/quarantine.jsonl` | Keeps rejected records next to the data they were rejected from |
