# ADR 0003: Acquire OCD data from ArcGIS and FTP, with no mirrors

**Status:** Accepted and implemented.

## Context

OCD data is reachable several ways, and no single route holds everything:

| Route | Holds | Finding on 2026-11-05 |
|---|---|---|
| `gis.emnrd.nm.gov` Wells_Public service | Current registry with coordinates | Official, 142,469 records, paged queries |
| `ftp.emnrd.nm.gov` OCD Interface v1.1 | Full table extracts, including production | Official, refreshed recently |
| University of New Mexico ArcGIS layer | OCD-derived wells | A third-party copy with only 55,572 records |
| GO-TECH (New Mexico Tech) | Access database of wells and production | Third party; its site says it is not the best place for all production records |

## Decision

Use the two official routes. Select wells from ArcGIS, take production and well history from FTP, and join only on the API number. Do not use mirrors, including as a fallback.

The FTP hostname was confirmed in two ways: OCD's FTP page gives the address `164.64.106.6` as an image, and reverse DNS for that address returns `ftp.emnrd.nm.gov`.

## Consequences

- Having two official systems allows a real cross-check of status, operator, coordinates, and production dates.
- FTP is unencrypted and OCD publishes no checksums. Stored SHA-256 values prove only that a file is unchanged since receipt, not what the publisher sent.
- The FTP files refresh often, so each batch records file timestamps, and `make acquire` reuses a finished batch unless asked to refresh.
- OCD's FTP notes that its GIS folder has moved to the Hub. The Interface v1.1 folder is still updated, but it could change, and the adapter would then fail loudly.
