# data/fixtures

Committed data for tests that run offline.

| Path | Contents |
|---|---|
| `petrobras_3w/` | Real 3W records truncated to 300 rows, cut by `scripts/cut_fixtures.py`. CC BY 4.0, Petrobras. `provenance.json` records the source hash of each file. |
| `carbon_mapper/` | Real Carbon Mapper plume and scene records cut to a few items, and one real scene vector tile. Non-commercial terms with attribution; see `carbon_mapper/NOTICE.md`. |
| `naip/stac_item.json` | The real STAC metadata of one NAIP image, with access tokens removed. The pixel crop used by one test stays in `data/fixtures_local/` because NAIP licensing for 2022 imagery is unconfirmed. |
| `ci_workspace/` | A small workspace in the shape of `data/`, built by `scripts/build_ci_fixtures.py`. |

**The OCD rows in `ci_workspace/` are hand-written test data, not source records.** OCD states no redistribution terms, so real OCD samples stay in `data/fixtures_local/`, which is gitignored. Their API numbers and names are made up, so nothing here should be read as a real well.
