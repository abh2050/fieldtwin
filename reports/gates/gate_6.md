# Gate 6 report: aerial evidence

**Status: revised after two reviews and stopped for re-review.** The work is on branch `gate-6` and isn't merged. The first review found two P1 defects and the re-review one more, all fixed (see [Review findings](#review-findings-and-what-changed)). The final local rebuild ran 34 steps, and all passed, including the live checks against the OCD FTP server, which had refused connections during earlier rebuilds. Hosted CI for this revision is recorded below once it has run.

Date: 2026-11-10. Branch: `gate-6`. Full output of the final local rebuild: [`gate_6_execution_log.txt`](gate_6_execution_log.txt). Decisions: [ADR 0018](../../docs/adr/0018-aerial-evidence-as-proximity.md).

> **Proximity is not attribution.** Real Carbon Mapper methane plumes and real USDA NAIP photographs are related to real New Mexico registry wells by distance and coverage only. Nothing here says a well is leaking, identifies an emission source, judges equipment condition, or describes AETHER Field, which is fictional.

## Headline

- **Two real sources acquired.** Carbon Mapper gave 455 methane plumes and 243 scenes over the Gate 1 townships, with no record quarantined. NAIP gave 60 windows of 300 m around registry wells, from 2022 imagery at 0.6 m, each centred within 0.74 m of its well.
- **Within observed scenes, plumes sit nearer registry wells than matched locations do, but proximity can't name a source.**
    - 158 of 455 plume origins (34.7%) lie within 250 m of a registry gas well, against 17.0% of points drawn inside the same scenes' footprints: +17.8 points (12.8 to 22.8, resampling the 142 scenes). With one plume per location group, the figures are 41.5% against 16.8%. At 1 km the difference is indistinguishable from zero.
    - Only 45 of those 158 plumes have exactly one candidate well; 72 have two to four and 41 have five or more.
    - The registry lists gas wells only, so tank batteries, compressors, oil wells, and pipelines nearby are missing.
- **Coverage:** 205 usable wells have a plume within 250 m, 439 sat inside a clear scene with no plume nearby, and 1 lies in no listed scene footprint. "No plume nearby" means nothing exceeded the detection limit at those overpasses, not that nothing was emitted.
- **Display text is templated, with a pattern guard as a backstop.** All card text comes from fixed templates, and a guard rejects leak, emission-verb, cause, attribution, defect, certainty, drone, and AETHER wording. On the rendered pages, 880 visible lines were checked, with 0 violations. The guard matches words, not meaning, so no free text is displayed as evidence.
- **Review and requests:** human review is blind, append-only, and holds vocabulary values only, with no free text. The model and the database both refuse a review that isn't blind, even from the application role. **No review has been recorded**, because none has been done and none was invented. One inspection request exists, for fictional asset A-03, generated from the AETHER-FAULT-001 synthetic event.

## Acceptance

The specification's Gate 6 deliverables are imagery ingestion, spatial coverage, emission observation associations, and inspection review. Its acceptance test is that "the application correctly displays evidence and does not make unsupported equipment-failure or emission-attribution claims."

| # | Criterion | Result | Evidence |
|---:|---|---|---|
| 1 | Imagery ingestion | **Met** | NAIP windows read from cloud-optimized GeoTIFFs, keeping acquisition date, ground sample distance, CRS, footprint, and source URL. Manifest, checksums, and read-only raw files. [Aerial sources](../ingestion/aerial_sources.md) |
| 2 | Methane observations ingested with their metadata | **Met** | Plume ID, time, location, emission estimate and its uncertainty, instrument, sector code, quality, and asset links, as the specification lists. Signed links are stored without signatures. |
| 3 | Spatial coverage | **Met** | True scene footprints from Carbon Mapper's public vector tiles, graded per well with the 25% cloud limit Carbon Mapper uses for candidate null detects. [Coverage](../inspection/coverage_and_review.md) |
| 4 | Emission observation associations | **Met** | `EMISSION_NEAR` only, `UNVERIFIED`, no confidence value, compared with a null drawn inside each plume's own scene footprint, with scene-resampled intervals, a persistent-source sensitivity, and candidate counts. [Spatial association](../inspection/spatial_association.md) |
| 5 | Inspection review | **Met, with no reviews recorded** | Blind review required in the model and the database. Outcome and visible features from fixed vocabularies, checked in the database; no free text. Each review's kind and evidence ID must match the observation it references. Append-only ledger with single supersession. Inspection requests for fictional assets only. |
| 6 | Displays evidence without unsupported claims | **Met for the evidence view model and generated pages** | Text from fixed templates, a pattern guard as a backstop on every sentence, fixed statements of what the evidence can't show, and attribution on every card. No free text is displayed. The application screens themselves are Gate 8, so this gate's display is a locally generated page. |
| 7 | Earlier gates still pass | **Met** | The rebuild from an empty database reran Gates 2 to 4. AETHER-FAULT-001 and all six field-scenario hashes match their recorded values. 242 database tests passed. 37 tests on real data passed, among them 2 earlier-gate reconciliation tests that failed in a first rebuild that left out the reconciliation stage. |
| 8 | Tests and CI | **Met locally; hosted CI for this revision pending** | 595 offline tests passed. 7 contract tests passed. Every CI command passed in a clean copy of the tracked files. After the first review, [all 9 hosted CI jobs passed](https://github.com/abh2050/fieldtwin/actions/runs/42877223549) on `b4d329a`. |

## How the evidence is limited

| What the data could tempt you to say | Why it isn't supported | What the design does |
|---|---|---|
| "This well is the source of this plume." | Most nearby plumes have several candidate wells; the registry omits other equipment; locations are approximate. | Only `EMISSION_NEAR`. The database refuses a verified proximity link, an unverified attribution, and changing a link's type. |
| "Plumes are near wells more than chance." | Plumes can only be detected where scenes were flown, so a whole-map comparison mixes in unobserved land. | A null drawn inside each plume's own scene footprint, resampled by scene. The whole-map figure is kept only as a labelled geometric reference. |
| "This well isn't emitting." | A scene only shows that nothing exceeded the detection limit at that moment. | `IMAGED_NO_PLUME_NEARBY`, with that caveat on every card. |
| "The photo shows a defect or a leak." | NAIP imagery carries no emission or equipment labels. | Context only. No computer vision is trained. Reviews hold vocabulary values only, so they can't record a leak or a defect. |
| "This plume is at AETHER Field." | AETHER is fictional and has local coordinates only. | Domain boundaries refuse Carbon Mapper and NAIP links to fictional assets. The claim guard rejects AETHER names in real evidence. |
| "Send a crew to this real well." | It's a real company's well, and the evidence is proximity. | Inspection requests reference fictional assets only and need a synthetic AETHER event of the same run. |

## Results

Version 2 of the association rules, after review. Each plume is compared with 200 points drawn inside the footprint of the scene that observed it; intervals resample the 142 scenes with plumes.

| Radius | Plumes with a well inside | Matched null | Difference (points) | 95% scene bootstrap |
|---|---:|---:|---:|---:|
| 100 m | 14.3% | 3.5% | +10.8 | +7.7 to +13.9 |
| 250 m (primary) | 34.7% | 17.0% | +17.8 | +12.8 to +22.8 |
| 500 m | 60.4% | 44.8% | +15.6 | +11.1 to +20.5 |
| 1,000 m | 74.5% | 72.3% | +2.2 | −2.1 to +6.5 |

With one plume per location group (147 groups of origins within 100 m), the 250 m figures are 41.5% against 16.8%, +24.7 points (15.7 to 33.3). The intervals are still optimistic: location groups only approximate persistent sources. The radius was fixed after the distance distribution had been looked at once, and the version 2 method was designed after the version 1 numbers were known. Both are disclosed in the [association report](../inspection/spatial_association.md).

Database after the rebuild: 455 plume observations, 60 image observations, 536 `EMISSION_NEAR` and 60 `IMAGE_COVERS` links (all `UNVERIFIED`), 1 inspection request, and 0 reviews. Loading a second time added no rows.

## Data and licensing

- **Carbon Mapper:** a revocable, non-commercial license with attribution (Terms of Use, effective 2026-01-13). Raw data isn't committed. Five plume records, three scene records, and one vector tile are committed as test fixtures, with the required notice.
- **NAIP:** licensing for 2022 imagery is **unconfirmed**. NAIP is documented as public domain only through 2019, Planetary Computer lists the license as "other", and the USDA page timed out. NAIP pixels are therefore never committed. One test that reads NAIP pixels uses a local fixture and skips in CI.
- **OCD:** as before, no real OCD rows are committed and no well is named in any published file. Gate 6 reports are aggregate. Per-well evidence pages are written to `data/gold/inspection/`, which isn't committed.

## Evidence

| Check | Result |
|---|---|
| Steps in the final rebuild | 34 of 34 passed, including 7 of 7 live endpoint checks. Earlier rebuilds on the same day failed only the 3 OCD FTP checks, while that server refused connections. |
| Raw integrity of the aerial batches | 140 Carbon Mapper files and 70 NAIP files rehashed, all read-only, and the aggregate checksums match. [`gate_6_validation.json`](gate_6_validation.json) |
| Offline tests | 595 passed |
| Database tests | 242 passed |
| Tests on real data | 37 passed |
| Clean copy of tracked files | Every CI command passed (587 unit and acquisition tests passed and 1 skipped, the NAIP pixel test) |
| Lint, format, types | Ruff and mypy clean |

## Review findings and what changed

| Finding | Fix | Evidence |
|---|---|---|
| **P1: the random-point baseline ignored observation coverage.** Plumes can only be detected where scenes were flown, so uniform points over the whole box partly compared plumes with unobserved land. | Rules version 2: each plume's null points are drawn inside its own scene footprint, clipped to the study area. Intervals resample scenes, and a one-plume-per-location-group sensitivity covers persistent sources. "Against chance" wording is gone; the whole-box figure remains only as a labelled geometric reference. | The conclusion held at 100 to 500 m (34.7% against 17.0% at 250 m) and vanished at 1 km. `test_matched_null_draws_inside_each_plumes_own_footprint` |
| **P1: blind review was not enforced, and free-text notes bypassed the guard.** `blinded_to_plume_status` accepted `false` in the model and the database, the application role could insert any note, and the guard missed paraphrases such as "This well released methane." | The blind flag is `true`-only in the model and the database. The note is removed; reviewers record visible features from a fixed vocabulary that the database checks. The guard gains emission verbs, and its documentation and the reports now call it a pattern backstop on templated text, not a semantic check. Migration 0014 was edited in place because it has never been merged. | `test_an_unblinded_review_is_refused_even_from_the_application_role`, `test_reviews_hold_only_vocabulary_values`, `test_reviews_hold_no_free_text_and_are_always_blind`, and five paraphrase cases in `test_guard_rejects_unsupported_claims` |

| **Re-review P1: a review could reference the wrong evidence.** The trigger checked only that the observation was aerial, so a direct insert could pair one observation with another plume's ID, or call a Carbon Mapper observation a NAIP chip. The earlier tests used an unrelated ID, `P1`, and it was accepted. | The review trigger now loads the observation's source system and source record ID, and requires `PLUME` with Carbon Mapper, `NAIP_CHIP` with NAIP, and `evidence_id` equal to the source record ID. It also refuses repeated visible features. The tests now use real plume IDs. | `test_review_identifier_must_name_its_observation`, `test_review_kind_must_match_the_observation_source`, `test_visible_features_are_distinct_in_the_database`, `test_a_correct_review_is_accepted_from_the_application_role` |

The blind flag records what this workflow showed the reviewer. It can't stop a person looking up plume data elsewhere.

## Process notes

- **A new NAIP batch was acquired during the rebuild.** The NAIP license text in the configuration changed after the first download, which changes the configuration hash, so the first rebuild acquired a fresh batch for the same 60 wells. The committed evidence comes from that batch, `naip-20261110-231dde276e`.
- **The first rebuild had six failed steps.** Its causes were one long line, a fixture record listing an uncommitted file, the missing reconciliation stage, and the OCD FTP outage. The first three are fixed. The log in this branch is from the rebuild after the re-review, in which every step passed.
- **One limit statement failed the claim guard during development.** "None of them describes AETHER Field" was rejected until "none" was added to the negation words, which shows the guard runs on its own fixed text.

## Limitations

1. The study area is two townships, and the registry is gas wells only. Proximity results don't generalize beyond it.
2. Scene footprints come from vector tiles and are quantized to the tile grid at zoom 12, roughly 10 m. 151 scenes in the tiles aren't returned by the scene list and are excluded.
3. 60 scenes report no cloud cover and never count as clear, which can understate coverage.
4. Carbon Mapper's emission uncertainty has no stated statistical meaning in the API, so it's recorded as `UNKNOWN`.
5. NAIP imagery is from 2022, and the plumes span 2019 to 2026. A chip shows a pad as it looked then.
6. No human review has been done.
7. The matched null holds observation exposure fixed but not where infrastructure sits within a scene, so it shows plumes are near wells and their pads, not that a well is a source.
8. The evidence page is generated locally. The application UI is Gate 8.

## Scope kept out

No source attribution, no computer vision, no maintenance prioritization or work orders (Gate 7), no application UI (Gate 8), no AWS resources, and no paid model calls.
