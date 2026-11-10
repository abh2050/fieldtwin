# ADR 0018: Aerial evidence is proximity and coverage, reviewed by people, never attribution

**Status:** Accepted and implemented in Gate 6.

## Context

Gate 6 brings in two real aerial sources: Carbon Mapper methane plume detections from aircraft and satellites, and USDA NAIP aerial photographs. Both sit naturally beside the real New Mexico registry wells from Gate 1. That makes it easy to slide from "a plume was detected near this well" to "this well is leaking", which the data can't support:

- The registry holds gas wells only. Tank batteries, compressors, flares, oil wells, and pipelines are absent.
- Plume origins are estimates, and Carbon Mapper says they may not match infrastructure on the ground. OCD calls its well locations approximate.
- Of the plumes with a registry well within 250 m, most have two or more candidate wells.
- Proximity also happens by chance: a random point in the study area is within 250 m of some well 16% of the time.

AETHER Field is fictional and has local coordinates only, so no real observation can describe it.

## Decision

**Proximity is the only plume relationship.** A plume is linked to every usable registry well within 250 m as `EMISSION_NEAR`, always `UNVERIFIED`, with no confidence value. The Pydantic contract has no field that could express attribution. The existing database constraints refuse a verified proximity link, a `SOURCE_ATTRIBUTED_TO` link without verified evidence, and a change of relationship type. Every report gives the random-point baseline and the number of candidate wells.

**Coverage is graded, not inferred.** A well inside a clear scene footprint with no plume nearby is `IMAGED_NO_PLUME_NEARBY`, which means nothing exceeded the detection limit at those moments. Footprints come from Carbon Mapper's public vector tiles. Scenes with unknown cloud cover never count as clear.

**Every displayed sentence passes a claim guard.** `packages/inspection/claims.py` rejects leak, cause, attribution, defect, certainty, drone, and AETHER claims unless negated. Evidence cards carry fixed statements of what the evidence can't show, plus attribution for both sources. Rendered pages are checked again line by line.

**Review is human, blinded, and append-only.** The review queue shows each NAIP chip by an opaque ID with nothing about plumes. Outcomes can note visible infrastructure, mark an image unusable, or suggest field verification. None can confirm a leak or name a source. Corrections supersede; the database refuses edits and deletions.

**Inspection requests are for fictional assets only.** They are generated from synthetic AETHER prioritization inputs. The table references `assets`, which holds fictional assets only, and a trigger refuses any event that isn't a synthetic AETHER event of the same run. No request is generated for a real well, because a plume near a real company's well is evidence for review, not grounds to send anyone there.

**Real evidence stays local.** Per-well evidence pages and NAIP chips are written under `data/`, which isn't committed. Committed reports are aggregate and name no well, plume, or chip.

**No computer vision.** No licensed, labeled defect or emission imagery is available, so no visual detector is trained, as the specification requires.

## Disclosures

- The plume-to-well distance distribution and the random-point baseline were looked at once, during source inspection, before the 250 m radius was fixed. Results at 100 m, 500 m, and 1 km are reported beside it.
- NAIP licensing for 2022 imagery is unconfirmed (see the license inventory), so chips are never committed. One test that needs NAIP pixels uses a local fixture and skips in CI.
- The application screens themselves are Gate 8. Gate 6 delivers the evidence view model, the claim guard, and a locally generated review page that the application will replace.

## Consequences

- Gate 7 can use the coverage and proximity records as context, but nothing in them is a risk score or a finding about a real asset.
- A source attribution would need evidence Gate 6 doesn't have, such as an operator's own records or a verified field visit. Adding one requires a new ADR.
- The review ledger is empty until a person reviews the images. None were invented.
