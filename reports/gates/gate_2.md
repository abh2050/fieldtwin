# Gate 2 report: canonical data model and semantic contracts

**Status: PASSED LOCALLY, conditional on the first hosted CI run.** Nine of the ten acceptance criteria are met with executed evidence. Criterion 8 is met except that the GitHub Actions workflow has never run on GitHub, because this repository has no commits or remote yet.

Date: 2026-11-05. Full output of the final rebuild: [`gate_2_execution_log.txt`](gate_2_execution_log.txt).

## Acceptance criteria

| # | Criterion | Result | Evidence |
|---:|---|---|---|
| 1 | Real source schemas inspected | **Met** | [`generated/nm_ocd.schema.json`](../../data_contracts/sources/generated/nm_ocd.schema.json) and [`petrobras_3w.schema.json`](../../data_contracts/sources/generated/petrobras_3w.schema.json), measured from every acquired record |
| 2 | Migrations run from a clean environment | **Met** | Docker volume deleted, then 8 migrations applied to PostgreSQL 16.4 with PostGIS 3.4. A second run applied 0. |
| 3 | Source data normalizes without losing lineage | **Met** | 36,754 of 36,754 production rows and 498 of 498 instances trace to a raw file, process, and batch. Volume totals match bronze exactly. |
| 4 | Units and grains verified or explicitly unresolved | **Met** | [`production_units.md`](../data_quality/production_units.md). All three units verified. `eff_dte` and missing oil or water rows are explicitly unresolved. |
| 5 | Invalid physical-semantic mappings rejected | **Met** | 51 database tests attempt violations, including `PT-P` to an onshore wellhead definition and `UNKNOWN` to `GAUGE` |
| 6 | Real and fictional identities separate | **Met** | Separate tables and foreign keys ([ADR 0006](../../docs/adr/0006-separate-real-and-fictional-assets.md)), with tests that attempt to cross them |
| 7 | Quality exceptions handled transparently | **Met** | 50 recorded exceptions with original values, evidence, and decisions (below) |
| 8 | Integration tests and CI validation pass | **Partly met** | All integration tests pass, and every CI command passes in a clean copy. **The workflow hasn't run on GitHub.** |
| 9 | 3W/AETHER compatibility report complete | **Met** | [`semantic_compatibility.md`](../reconciliation/semantic_compatibility.md): 30 of 30 variables and 10 of 10 event classes classified with reasoning |
| 10 | Documentation matches the implemented schema | **Met** | [`canonical_schema.md`](../data_quality/canonical_schema.md) is generated from the catalog, and a test fails if it differs |

## Executed results

| Step | Result |
|---|---|
| Offline tests (`pytest`) | 129 passed |
| PostgreSQL integration tests | 35 passed |
| Provenance invariants against PostgreSQL | 51 passed |
| Tests on real canonical and acquired data | 17 passed |
| Canonical validation against real bronze | 21 of 21 checks passed |
| Raw integrity re-hash (`make validate`) | Passed |
| Ruff lint and format, mypy on 35 files | Passed |
| OCD bronze quality checks | 16 pass, 3 warn, 0 fail |
| 3W bronze quality checks | 7 pass, 0 warn, 0 fail |
| `pip-audit` on the locked dependency list | No known vulnerabilities |
| `gitleaks` on the tracked files | No leaks found |
| `actionlint` on the workflow | No findings |

The clean-copy run (`scripts/ci_local.sh`) copied only the tracked files, with no raw or bronze data, and ran each workflow command with 0 failures.

The live endpoint tests from Gate 1 were not rerun, because Gate 2 acquired nothing new.

## Canonical data

| Item | Count |
|---|---:|
| Tables, including the migration ledger | 35 |
| New Mexico wells (real) | 681 |
| Well completions (real) | 441 |
| Well-history rows | 1,098 |
| Production rows | 36,754 |
| 3W wells (real, anonymized) | 40 |
| 3W instances (342 `OBSERVED`, 156 `SYNTHETIC`) | 498 |
| Per-sensor series metadata rows | 13,446 |
| Field-level reconciliation records | 2,724 |
| AETHER assets (fictional, `SYNTHETIC`) | 27 |
| Scenario mappings and experimental links | 0 |

## Measurement semantics

`v_tag_semantics` gives all nine required attributes for each of the 27 3W sensors. All 10 pressure tags remain `UNKNOWN` and are marked `SEMANTICS_INCOMPLETE`. Each tag maps only to a definition in its own offshore equipment class. The database can't store a mapping across classes or reference types, because composite foreign keys cover both ([ADR 0009](../../docs/adr/0009-measurement-semantics-by-equipment-class.md)).

## Production units

Verified against OCD's data dictionary, the 2019 and 2025 C-115 instructions, and 19.15.2.7 NMAC:

| Code | Unit | Scope |
|---|---|---|
| `G` | MCF at 15.025 psia and 60 degrees F | Gas, **including CO2** |
| `O` | Barrels (42 US gal at 60 degrees F) | Crude oil **or condensate** |
| `W` | Barrels (42 US gal at 60 degrees F) | Produced water |

The grain is well completion, month, and product. The production date comes from `prodn_yr` and `prodn_mth`. An amended report replaces the earlier one at the source, so revision history isn't available.

## Quality exceptions and decisions

| Exception | Count | Disposition | Decision |
|---|---:|---|---|
| Coordinate inconsistent with PLSS township | 1 | Quarantined from spatial analytics, open | Well `30-015-53569` is 112.1 km from the median of its 334 township peers, with the same value in both OCD channels. The reported value is kept and no correction is assumed. Its production records stay valid. |
| Datum labels conflict (ArcGIS NAD27, FTP NAD83) | 30 | Flagged, open | Not guessed. No analytic geometry. |
| Datum label missing in ArcGIS | 5 | Flagged, open | Handled the same way as a conflict, even though FTP says NAD83. |
| 3W pressure reference unknown | 10 tags | Flagged, open | Stays `UNKNOWN`. |
| Closed history rows at coordinates 0, 0 | 4 | Quarantined at acquisition, accepted | Visible in the database and not loaded as history. |

The spatial population is 645 usable, 1 quarantined, and 35 unresolved, which adds up to the 681 wells.

**Thresholds were tightened, not weakened.** Gate 1 had changed one coordinate check after seeing a failure, allowing up to 1% of wells outside the county box. That allowance is gone. Any well outside the box now fails unless the quarantine rule catches it, and canonical validation allows zero in the usable population. The rule uses distance from township peers and contains no well IDs, and on real data it flagged exactly the one known bad well.

The 3 remaining OCD warnings are visible by design: the raw outlier count, the datum conflicts, and the quarantined rows. Each is covered in the table above.

## 3W compatibility

| Classification | Variables | Event classes |
|---|---:|---:|
| Directly compatible | 0 | 0 |
| Conditionally compatible | 8 | 2 |
| Incompatible | 14 | 5 |
| Insufficient evidence | 8 | 3 |

3W stays a separate offshore benchmark ([ADR 0010](../../docs/adr/0010-3w-benchmark-and-synthetic-telemetry.md)). The two conditional event classes are `QUICK_RESTRICTION_IN_PCK` and `RAPID_PRODUCTIVITY_LOSS`. A database trigger refuses a scenario mapping for any incompatible or insufficient-evidence class. No mapping exists today, and no model was trained.

## Documentation review

`docs/index.html` was rendered in Chrome at desktop width and in a 390 px frame, and all three draw.io pages were exported and reviewed.

| Finding | Fix |
|---|---|
| AWS page: an arrow crossed the Bedrock box, whose text also wrapped badly | Rearranged the page |
| Logical page: out of date and implied 3W fed AETHER, and later two boxes were overfull | Updated and shortened |
| New boundaries page: first draft had arrows through boxes | Rearranged |
| Landing page: long paths ran past the edge on a phone | Paths now wrap |

An apparent clipping in the first phone screenshot came from Chrome's headless minimum window width, not the page.

## Repository metadata

- The one company reference was in `instructions.md`, and it is removed along with leftover pasted citation text. A test now fails if it returns. No recruiter correspondence was found in the project files.
- `main` has no commits, so no git history needs rewriting.
- **Fixtures:** OCD publishes no redistribution terms, so real OCD samples moved to the gitignored `data/fixtures_local/`, and CI uses hand-written rows labeled as such. 3W fixtures are real, truncated, and CC BY 4.0 ([ADR 0011](../../docs/adr/0011-spatial-quarantine-and-fixtures.md)).
- Raw and bronze data, credentials, and model artifacts are not tracked. The largest tracked file is 260 KB.

## Failures during this gate

| Failure | Resolution |
|---|---|
| First real load failed on a PostgreSQL parameter type in the geometry insert | Pass explicit geometry coordinates, set only for usable assets |
| 2 of 86 first-run database tests failed, both from test mistakes (wrong expected error type, comparing `Decimal` with a NumPy integer) | Tests corrected. The database had refused the bad mapping correctly. |
| 24 mypy errors on first run | Fixed in the code |
| Evidence run 1: lint, format, and `pip-audit` failed | Fixed the lint and format. `pip-audit` crashed creating its own pip environment on macOS, and it now audits the fully pinned export directly. |
| `actionlint` first ran outside a git project and checked nothing | Run in a directory with `git init`, as `ci_local.sh` does |

## Limitations

1. **Hosted CI hasn't run.** `actionlint` and the clean-copy run reduce the risk but don't replace a real run. `gitleaks` ran on the file tree only, while the workflow scans git history, which doesn't exist yet.
2. **PostGIS runs under amd64 emulation here,** because the image has no usable arm64 build. CI uses amd64 natively.
3. **Real-data checks are local only.** CI proves parsing and loading on realistic shapes, because real OCD rows aren't committed.
4. **Compatibility is engineering judgment.** No field engineer or hydraulic calculation validated it, and AETHER's equipment is a chosen design.
5. **OCD redistribution terms are unresolved.** New Mexico's public records law wasn't analyzed. Reports cite one API number and its coordinate, plus aggregate volumes.
6. **The units rule copy runs through 8/23/2022.** Later amendments weren't checked. Operator compliance can't be verified from this data.
7. **Database controls guard against mistakes,** not a superuser who disables them. The DynamoDB path will need its own enforcement.
8. **Operational tables are structure only.** Inspection, prediction, work-order, and approval workflows arrive in later gates. Repository interfaces and DynamoDB adapters aren't built.
9. **The OCD cross-checks still aren't independent.** The schema now records that explicitly with `channels_are_independent = false`.

## Decisions needed

1. **Commit and first CI run.** Once you approve a commit and a remote, the first hosted run settles criterion 8.
2. **AETHER-FAULT-001.** Section 22 of the specification still describes replaying a 3W event. It needs revising around synthetic telemetry before Gates 3 to 5 rely on it (ADR 0010).
3. **Public release.** Decide whether the cited API number and aggregate volumes are acceptable given OCD's unstated terms.

## Next actions

Gate 3 is not started. It can begin once the decisions above are made, starting with reconciliation on the canonical records and a scoped design for synthetic telemetry.
