# Gate 1 report: source acquisition

**Status: PASSED, with the limits listed below** on 2026-11-05.

**Acceptance criterion:** at least the primary registry and telemetry sources are acquired and independently validated.

The criterion is met in full for 3W. For OCD, validation is limited: the data was cross-checked between two OCD systems, which is not validation independent of OCD (see [Limits](#limits-on-this-result)).

## Evidence

| Check | Result | Record |
|---|---|---|
| Offline tests | 79 passed, 0 failed | [`test_results.txt`](test_results.txt) |
| Tests on acquired data | 5 passed, 0 failed | same |
| Live endpoint tests | 5 passed, 0 failed | same |
| `make validate` (re-hash raw, check manifests and reports) | Passed: 509 files, 0 integrity problems | [`gate_1_validation.json`](gate_1_validation.json) |
| OCD quality checks | 15 PASS, 3 WARN, 0 FAIL | [`nm_ocd.md`](../data_quality/nm_ocd.md) |
| 3W quality checks | 7 PASS, 0 WARN, 0 FAIL | [`petrobras_3w.md`](../data_quality/petrobras_3w.md) |
| Re-run of `make acquire` | Both batches reused in 1 second; manifests byte-identical | Executed manually |
| Write to a raw file | Refused: files are read-only | Executed manually |

## Sources accessed

| Source | Status |
|---|---|
| OCD ArcGIS `gis.emnrd.nm.gov` | Acquired |
| OCD FTP `ftp.emnrd.nm.gov` | Acquired |
| Petrobras 3W at a pinned commit | Acquired |
| Carbon Mapper, USDA NAIP | Deferred to Gate 6 and not inspected, as section 25 limits this stage to OCD and 3W |

## Records acquired

| Source | Records | Raw size |
|---|---|---:|
| OCD wells | 681 (target 500-1,000) | 988 MB in total |
| OCD well history | 1,098 rows, 4 quarantined | |
| OCD production | 36,754 rows for 438 wells and 441 completions, 2023-12 to 2026-09 (48.4 million scanned) | |
| 3W | 498 instances, 28,226,175 observations, 40 real wells | 541 MB |

Checksums and per-class counts are in the [acquisition summary](../ingestion/acquisition_summary.md). Manifests are in [`data/manifests/`](../../data/manifests/). Licenses are in the [license inventory](../../docs/datasets/license_inventory.md).

## Schema findings

**OCD**

- Exports are UTF-16 XML that compress about 20:1, so they are read as a stream ([ADR 0004](../../docs/adr/0004-stream-production-xml.md)).
- Production is reported per well completion, month, and product, not per lease. No allocation was needed or done.
- Each completion, month, and product has exactly one row, so the extract holds current values only. 65% of rows are amended, and earlier values aren't available.
- `eff_dte` is a filing time in recent rows, not the production date.
- Status "New" doesn't mean non-producing: 151 of 256 New wells have production rows.

**3W**

- There are three origins, not two: real, simulated, and hand-drawn. Only real is `OBSERVED`.
- Sampling is 1 second across all selected instances. 48% of real sensor cells are empty, and many sensors are empty for entire instances.
- `class` can be null, 0, the event label, or the label + 100. 1,231,200 rows have null `class` and `state`.
- `dataset.ini` gives units but no pressure reference type, so it stays `UNKNOWN`.

## Findings in the source data

| Finding | Handling |
|---|---|
| Well `30-015-53569` is listed about 1 degree north of its PLSS township neighbors, in both OCD systems. It has no production rows in the window. | Kept as reported and named in the quality report. It must be excluded or resolved before Gate 3 geospatial work. |
| 35 wells have conflicting datum labels for identical coordinates: 30 are NAD27 in ArcGIS and NAD83 in FTP, and 5 are blank in ArcGIS. | Kept as reported. The datum of these wells is unresolved. |
| 4 closed well-history rows have coordinates of 0, 0. | Quarantined with a reason. |

## Limits on this result

1. **OCD cross-checks are not independent.** ArcGIS and FTP gave identical status, operator, and coordinates for every well, so they appear to be views of one database. Agreement shows consistent delivery. It doesn't confirm the data is correct, and the coordinate error above proves it can be wrong in both.
2. **No inspection data was acquired.** The dictionary's 22 tables include none for inspections. A separate OCD system might hold them, and that hasn't been ruled out. Nothing was generated in its place.
3. **OCD has no stated license.** The data is public, but no license grants reuse terms. The fixtures contain 50 real OCD rows and 25 registry features, so review this before making the repository public.
4. **OCD integrity is limited.** With no publisher checksums and unencrypted FTP, hashes prove only that files are unchanged since receipt.
5. **The volume unit mapping is unconfirmed.** The dictionary says "MCF or BBLS" without assigning units to product kinds. Gas as MCF and liquids as BBLS is an interpretation for Gate 2 to record.
6. **The production window has about 33 complete months.** September 2026 has only 49 rows, which fits OCD's stated 45-day reporting lag. Month-to-month continuity per well was not checked.
7. **ArcGIS is unversioned.** Its pages reflect the retrieval date and can't be fetched again in the same state.
8. **Failure paths were tested with fakes.** Outages, truncated files, tampering, and low disk ran against test doubles, not real outages.

## Corrections made during this gate

Profiling first reported that 100% of production rows had an invalid effective date. Investigation showed that my rule was wrong, not the data, and date inference had also silently dropped 161 values. The check was replaced with a valid one and strict parsing, with tests added.

The rule for wells outside the county box was also changed after seeing the result, from FAIL on any outlier to WARN up to 1% and FAIL above that. This turned one FAIL into a WARN. The reasoning is that a single bad coordinate is a source error to report, not a failed acquisition, but a reviewer should know the threshold was set after the fact.

## Decision needed before Gate 3

**3W may not physically fit AETHER Field.** 3W comes from offshore oil wells with subsea trees and gas lift, while AETHER's wells are onshore natural gas. Section 8 requires rejecting physically implausible mappings, and several classes, such as DHSV closure and service-line hydrates, may have no counterpart. AETHER-FAULT-001 depends on at least one compatible event. Candidates need an explicit assessment, and the honest outcome may be a narrow mapping labeled as a demonstration of the mechanism.

**Evaluation data is thin in places.** Classes 3 and 6 have 2 real wells each, and classes 1, 5, and 6 have 11 or fewer real instances. Well-grouped evaluation in Gate 5 will be weak for those classes.

## Later changes (Gate 2)

This report records the state at Gate 1. Gate 2 removed the 1% outlier allowance, quarantined the bad coordinate from spatial analytics, verified the volume units, moved real OCD fixtures out of the repository, and kept 3W as a separate benchmark. See [`gate_2.md`](gate_2.md).

## Next actions

1. Gate 2: SQL schema, migrations, Pydantic contracts, and data dictionaries for the canonical model, normalizing these bronze records.
2. Record the volume-unit interpretation and sentinel handling in Gate 2.
3. Assess 3W compatibility before designing scenario mappings in Gates 3 and 4.
4. Check whether OCD inspection records exist in another system.
5. Add a GitHub Actions workflow running the offline suite.
