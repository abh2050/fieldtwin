# Gate 6 report: aerial evidence

**Status: implemented and stopped for technical review.** The work is on branch `gate-6` and isn't merged. The final local rebuild ran 34 steps, and one failed: three live checks against the OCD FTP server, which refused connections throughout the run. Gate 6 doesn't use that server. Hosted CI is recorded below once it has run.

Date: 2026-11-10. Branch: `gate-6`. Full output of the final local rebuild: [`gate_6_execution_log.txt`](gate_6_execution_log.txt). Decisions: [ADR 0018](../../docs/adr/0018-aerial-evidence-as-proximity.md).

> **Proximity is not attribution.** Real Carbon Mapper methane plumes and real USDA NAIP photographs are related to real New Mexico registry wells by distance and coverage only. Nothing here says a well is leaking, identifies an emission source, judges equipment condition, or describes AETHER Field, which is fictional.

## Headline

- **Two real sources acquired.** Carbon Mapper gave 455 methane plumes and 243 scenes over the Gate 1 townships, with no record quarantined. NAIP gave 60 windows of 300 m around registry wells, from 2022 imagery at 0.6 m, each centred within 0.74 m of its well.
- **Plumes sit near wells more often than chance, but proximity can't name a source.**
    - 158 of 455 plume origins (34.7%) lie within 250 m of a registry gas well, against 15.9% of random points in the same area.
    - Only 45 of those 158 plumes have exactly one candidate well; 72 have two to four and 41 have five or more.
    - The registry lists gas wells only, so tank batteries, compressors, oil wells, and pipelines nearby are missing.
- **Coverage:** 205 usable wells have a plume within 250 m, 439 sat inside a clear scene with no plume nearby, and 1 lies in no listed scene footprint. "No plume nearby" means nothing exceeded the detection limit at those overpasses, not that nothing was emitted.
- **Display is guarded.** Every sentence on an evidence card passes a claim guard that rejects leak, cause, attribution, defect, certainty, drone, and AETHER claims. On the rendered pages, 880 visible lines were checked, with 0 violations.
- **Review and requests:** blinded, append-only human review is built and enforced by the database. **No review has been recorded**, because none has been done and none was invented. One inspection request exists, for fictional asset A-03, generated from the AETHER-FAULT-001 synthetic event.

## Acceptance

The specification's Gate 6 deliverables are imagery ingestion, spatial coverage, emission observation associations, and inspection review. Its acceptance test is that "the application correctly displays evidence and does not make unsupported equipment-failure or emission-attribution claims."

| # | Criterion | Result | Evidence |
|---:|---|---|---|
| 1 | Imagery ingestion | **Met** | NAIP windows read from cloud-optimized GeoTIFFs, keeping acquisition date, ground sample distance, CRS, footprint, and source URL. Manifest, checksums, and read-only raw files. [Aerial sources](../ingestion/aerial_sources.md) |
| 2 | Methane observations ingested with their metadata | **Met** | Plume ID, time, location, emission estimate and its uncertainty, instrument, sector code, quality, and asset links, as the specification lists. Signed links are stored without signatures. |
| 3 | Spatial coverage | **Met** | True scene footprints from Carbon Mapper's public vector tiles, graded per well with the 25% cloud limit Carbon Mapper uses for candidate null detects. [Coverage](../inspection/coverage_and_review.md) |
| 4 | Emission observation associations | **Met** | `EMISSION_NEAR` only, `UNVERIFIED`, no confidence value, with a chance baseline and candidate counts. [Spatial association](../inspection/spatial_association.md) |
| 5 | Inspection review | **Met, with no reviews recorded** | Blinded queue, a limited set of outcomes, append-only ledger, and supersession, enforced in Python and in the database. Inspection requests for fictional assets only. |
| 6 | Displays evidence without unsupported claims | **Met for the evidence view model and generated pages** | Claim guard on every sentence, fixed statements of what the evidence can't show, and attribution on every card. The application screens themselves are Gate 8, so this gate's display is a locally generated page. |
| 7 | Earlier gates still pass | **Met** | The rebuild from an empty database reran Gates 2 to 4. AETHER-FAULT-001 and all six field-scenario hashes match their recorded values. 236 database tests passed. 37 tests on real data passed, among them 2 earlier-gate reconciliation tests that failed in a first rebuild that left out the reconciliation stage. |
| 8 | Tests and CI | **Met locally; hosted CI pending** | 588 offline tests passed. 7 contract tests passed. Every CI command passed in a clean copy of the tracked files. |

## How the evidence is limited

| What the data could tempt you to say | Why it isn't supported | What the design does |
|---|---|---|
| "This well is the source of this plume." | Most nearby plumes have several candidate wells; the registry omits other equipment; locations are approximate. | Only `EMISSION_NEAR`. The database refuses a verified proximity link, an unverified attribution, and changing a link's type. |
| "This well isn't emitting." | A scene only shows that nothing exceeded the detection limit at that moment. | `IMAGED_NO_PLUME_NEARBY`, with that caveat on every card. |
| "The photo shows a defect or a leak." | NAIP imagery carries no emission or equipment labels. | Context only. No computer vision is trained. Review outcomes can't record a leak or a defect. |
| "This plume is at AETHER Field." | AETHER is fictional and has local coordinates only. | Domain boundaries refuse Carbon Mapper and NAIP links to fictional assets. The claim guard rejects AETHER names in real evidence. |
| "Send a crew to this real well." | It's a real company's well, and the evidence is proximity. | Inspection requests reference fictional assets only and need a synthetic AETHER event of the same run. |

## Results

| Radius | Plumes with a well inside | Random points | Ratio |
|---|---:|---:|---:|
| 100 m | 14.3% | 3.2% | 4.4 |
| 250 m (primary) | 34.7% | 15.9% | 2.2 |
| 500 m | 60.4% | 41.9% | 1.4 |
| 1,000 m | 74.5% | 69.5% | 1.1 |

Plumes repeat at persistent sources, so these shares aren't independent trials and carry no intervals. The radius was fixed after the distance distribution had been looked at once, which is why the other radii are reported beside it.

Database after the rebuild: 455 plume observations, 60 image observations, 536 `EMISSION_NEAR` and 60 `IMAGE_COVERS` links (all `UNVERIFIED`), 1 inspection request, and 0 reviews. Loading a second time added no rows.

## Data and licensing

- **Carbon Mapper:** a revocable, non-commercial license with attribution (Terms of Use, effective 2026-01-13). Raw data isn't committed. Five plume records, three scene records, and one vector tile are committed as test fixtures, with the required notice.
- **NAIP:** licensing for 2022 imagery is **unconfirmed**. NAIP is documented as public domain only through 2019, Planetary Computer lists the license as "other", and the USDA page timed out. NAIP pixels are therefore never committed. One test that reads NAIP pixels uses a local fixture and skips in CI.
- **OCD:** as before, no real OCD rows are committed and no well is named in any published file. Gate 6 reports are aggregate. Per-well evidence pages are written to `data/gold/inspection/`, which isn't committed.

## Evidence

| Check | Result |
|---|---|
| Steps in the final rebuild | 34, 33 passed. The failure is the live-endpoint step: 3 OCD FTP checks failed with "connection refused", and 4 passed (Carbon Mapper, NAIP, ArcGIS, and the pinned 3W commit). |
| Raw integrity of the aerial batches | 140 Carbon Mapper files and 70 NAIP files rehashed, all read-only, and the aggregate checksums match. [`gate_6_validation.json`](gate_6_validation.json) |
| Offline tests | 588 passed |
| Database tests | 236 passed |
| Tests on real data | 37 passed |
| Clean copy of tracked files | Every CI command passed (580 unit and acquisition tests passed and 1 skipped, the NAIP pixel test) |
| Lint, format, types | Ruff and mypy clean |

## Process notes

- **A new NAIP batch was acquired during the rebuild.** The NAIP license text in the configuration changed after the first download, which changes the configuration hash, so the first rebuild acquired a fresh batch for the same 60 wells. The committed evidence comes from that batch, `naip-20261110-231dde276e`.
- **The first rebuild had six failed steps.** Its causes were one long line, a fixture record listing an uncommitted file, the missing reconciliation stage, and the OCD FTP outage. The first three are fixed. The log in this branch is from the second rebuild.
- **One limit statement failed the claim guard during development.** "None of them describes AETHER Field" was rejected until "none" was added to the negation words, which shows the guard runs on its own fixed text.

## Limitations

1. The study area is two townships, and the registry is gas wells only. Proximity results don't generalize beyond it.
2. Scene footprints come from vector tiles and are quantized to the tile grid at zoom 12, roughly 10 m. 151 scenes in the tiles aren't returned by the scene list and are excluded.
3. 60 scenes report no cloud cover and never count as clear, which can understate coverage.
4. Carbon Mapper's emission uncertainty has no stated statistical meaning in the API, so it's recorded as `UNKNOWN`.
5. NAIP imagery is from 2022, and the plumes span 2019 to 2026. A chip shows a pad as it looked then.
6. No human review has been done.
7. The evidence page is generated locally. The application UI is Gate 8.

## Scope kept out

No source attribution, no computer vision, no maintenance prioritization or work orders (Gate 7), no application UI (Gate 8), no AWS resources, and no paid model calls.
