# ADR 0018: Aerial evidence is proximity and coverage, reviewed by people, never attribution

**Status:** Accepted and implemented in Gate 6.

## Context

Gate 6 brings in two real aerial sources: Carbon Mapper methane plume detections from aircraft and satellites, and USDA NAIP aerial photographs. Both sit naturally beside the real New Mexico registry wells from Gate 1. That makes it easy to slide from "a plume was detected near this well" to "this well is leaking", which the data can't support:

- The registry holds gas wells only. Tank batteries, compressors, flares, oil wells, and pipelines are absent.
- Plume origins are estimates, and Carbon Mapper says they may not match infrastructure on the ground. OCD calls its well locations approximate.
- Of the plumes with a registry well within 250 m, most have two or more candidate wells.
- Proximity also happens by chance: a point drawn inside the same scene footprints as the plumes is within 250 m of some well 17% of the time.

AETHER Field is fictional and has local coordinates only, so no real observation can describe it.

## Decision

**Proximity is the only plume relationship.** A plume is linked to every usable registry well within 250 m as `EMISSION_NEAR`, always `UNVERIFIED`, with no confidence value. The Pydantic contract has no field that could express attribution. The existing database constraints refuse a verified proximity link, a `SOURCE_ATTRIBUTED_TO` link without verified evidence, and a change of relationship type. Every report gives a footprint-matched null and the number of candidate wells.

**Coverage is graded, not inferred.** A well inside a clear scene footprint with no plume nearby is `IMAGED_NO_PLUME_NEARBY`, which means nothing exceeded the detection limit at those moments. Footprints come from Carbon Mapper's public vector tiles. Scenes with unknown cloud cover never count as clear.

**Displayed text comes from fixed templates, with a pattern guard as a backstop.** `packages/inspection/claims.py` rejects leak, emission-verb, cause, attribution, defect, certainty, drone, and AETHER wording unless negated. It matches words, not meaning, so it isn't a semantic check and doesn't certify free prose. Evidence cards carry fixed statements of what the evidence can't show, plus attribution for both sources. Rendered pages are checked again line by line.

**Review is human, blind, append-only, and free of free text.** The review queue shows each NAIP chip by an opaque ID with nothing about plumes, and the model and the database refuse a review not marked blind. A reviewer records an outcome and visible features from fixed vocabularies; there is no note field, so nothing displayed from a review can assert a leak, a source, or a defect. Corrections supersede; the database refuses edits and deletions.

**Inspection requests are for fictional assets only.** They are generated from synthetic AETHER prioritization inputs. The table references `assets`, which holds fictional assets only, and a trigger refuses any event that isn't a synthetic AETHER event of the same run. No request is generated for a real well, because a plume near a real company's well is evidence for review, not grounds to send anyone there.

**Real evidence stays local.** Per-well evidence pages and NAIP chips are written under `data/`, which isn't committed. Committed reports are aggregate and name no well, plume, or chip.

**No computer vision.** No licensed, labeled defect or emission imagery is available, so no visual detector is trained, as the specification requires.

## Disclosures

- The plume-to-well distance distribution and the random-point baseline were looked at once, during source inspection, before the 250 m radius was fixed. Results at 100 m, 500 m, and 1 km are reported beside it.
- NAIP licensing for 2022 imagery is unconfirmed (see the license inventory), so chips are never committed. One test that needs NAIP pixels uses a local fixture and skips in CI.
- The application screens themselves are Gate 8. Gate 6 delivers the evidence view model, the claim guard, and a locally generated review page that the application will replace.

## Revision after technical review

Review found two defects, and both are fixed.

1. **The baseline ignored where Carbon Mapper looked.** Version 1 compared plumes with uniform points over the whole study box, but plumes can only be detected inside observed scenes, and the median scene with a plume covers 19% of the box. Version 2 draws each plume's null points inside the footprint of the scene that observed it, and resamples scenes for the interval, with a one-plume-per-location-group sensitivity for persistent sources. The uniform box is kept only as a labelled geometric reference. The conclusion survived the correction (34.7% against 17.0% within 250 m), but the version 1 wording overstated what the old baseline showed. Version 2 was designed and run after the version 1 numbers were known.
2. **Blind review and the claim boundary were not enforced.** The blind flag accepted `false` in both the model and the database, and the free-text note reached the database without the guard. The flag is now `true`-only in both, the note is replaced by a feature vocabulary checked in the database, and the guard gains emission-verb paraphrases. Its documentation now says what it is: a pattern backstop on generated text, not a semantic check.

Migration 0014 was changed in place rather than amended, because it has never been merged or applied outside development databases.

## Consequences

- Gate 7 can use the coverage and proximity records as context, but nothing in them is a risk score or a finding about a real asset.
- A source attribution would need evidence Gate 6 doesn't have, such as an operator's own records or a verified field visit. Adding one requires a new ADR.
- The review ledger is empty until a person reviews the images. None were invented.
