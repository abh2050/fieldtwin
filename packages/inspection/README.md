# packages/inspection

Aerial inspection evidence for Gate 6. Real Carbon Mapper plumes and USDA NAIP imagery are associated with
real registry wells by **proximity only**. Nothing here attributes an emission to a source, labels an
equipment defect, or links real evidence to fictional AETHER assets.

| Module | Purpose |
|---|---|
| `contracts.py` | Typed records. `ProximityLink` is always `EMISSION_NEAR`, `UNVERIFIED`, with no confidence value. |
| `geodesy.py` | Great-circle distances in metres. |
| `association.py` | Plume-to-well proximity links and the random-point chance baseline. |
| `coverage.py` | Whether each well fell inside a scene footprint, and under what cloud cover. |
| `claims.py` | The guard every displayed sentence passes. Unsupported claims raise. |
| `evidence.py` | The display view model, with attribution and fixed statements of what the evidence can't show. |
| `review.py` | Append-only human review ledger. No outcome can confirm a leak or name a source. |
| `requests.py` | Inspection requests, only for fictional AETHER assets from synthetic scenario events. |
