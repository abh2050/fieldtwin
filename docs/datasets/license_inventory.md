# Source and license inventory

Last checked 2026-11-10. This is an engineering record, not legal advice.

| Source | Status | License as stated | Constraints |
|---|---|---|---|
| New Mexico OCD | Acquired | **No explicit license found.** Pages describe it as "publicly available data and documents." | Do not call it openly licensed. Raw data is not committed. Attribute to NM OCD. The EMNRD disclaimer says the site does "not constitute an official or final repository" and takes no responsibility for errors or omissions. Locations are approximate. |
| Petrobras 3W | Acquired | Data: CC BY 4.0. Code: Apache 2.0 (repository README and `LICENSE.md`). | Attribution required. Cite per `CITATION.md`, stored with each batch. |
| Carbon Mapper | Acquired (Gate 6) | Carbon Mapper Terms of Use, effective 2026-01-13: a limited, revocable, non-commercial license. No Creative Commons license is referenced. | Non-commercial use only. Attribution required ("Data by Carbon Mapper®. Source: Carbon Mapper (data.carbonmapper.org)"). Redistribution must carry the same terms. Copies must be deleted if the license ends. No rate limit is stated; requests are spaced 1 s apart. Raw data is not committed; a few fixture records are, with the notice. |
| USDA NAIP | Acquired (Gate 6) | **Not confirmed for 2022 imagery.** Documented as public domain for imagery through 2019. Planetary Computer lists the license as "other" with USDA FSA as licensor. | Access is under the Microsoft Planetary Computer terms of use. Chips are not committed or redistributed until the license is confirmed. Credit "USDA NAIP". Context only, never labels. |
| AETHER synthetic records | Gate 4 | Project-generated | Must be labeled `SYNTHETIC`. |

Carbon Mapper and NAIP were deferred at Gate 1, as allowed, and acquired in Gate 6.

## Fixtures

3W fixtures are real truncated records under CC BY 4.0. OCD publishes no redistribution terms, so real OCD samples stay in the gitignored `data/fixtures_local/`, and CI uses hand-written OCD-shaped rows ([ADR 0011](../adr/0011-spatial-quarantine-and-fixtures.md)).

The search for terms covered OCD's data pages and the EMNRD legal disclaimer. New Mexico's public records law wasn't analyzed. To commit real OCD rows, ask EMNRD's records custodian or get legal advice first.

## Attribution text

> Well, operator, and production records: New Mexico Oil Conservation Division, Energy, Minerals and Natural Resources Department.
>
> Telemetry: Petrobras 3W Dataset, licensed under CC BY 4.0. https://github.com/petrobras/3W

## Known data gap: inspections

The spec asks for OCD inspection history "where accessible." The Interface v1.1 data dictionary lists 22 tables and none covers inspections, so none was acquired. A separate OCD system may hold them, and this has not been ruled out.
