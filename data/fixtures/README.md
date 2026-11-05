# data/fixtures

Committed data for tests that run offline.

| Path | Contents |
|---|---|
| `petrobras_3w/` | Real 3W records truncated to 300 rows, cut by `scripts/cut_fixtures.py`. CC BY 4.0, Petrobras. `provenance.json` records the source hash of each file. |
| `ci_workspace/` | A small workspace in the shape of `data/`, built by `scripts/build_ci_fixtures.py`. |

**The OCD rows in `ci_workspace/` are hand-written test data, not source records.** OCD states no redistribution terms, so real OCD samples stay in `data/fixtures_local/`, which is gitignored. Their API numbers and names are made up, so nothing here should be read as a real well.
