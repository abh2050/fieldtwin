# Acquisition summary

Run on 2026-11-05. Full manifests are in [`data/manifests/`](../../data/manifests/), and quality results are in [`reports/data_quality/`](../data_quality/).

No acquisition failed on the final runs, so there is no `*_failure_latest.json` file here.

## New Mexico OCD

Batch `nm_ocd-20261105-15ddeb88ae`. Aggregate checksum `b9c20868ea5f5a051619cc2301f422f2b7ff904402b592bd61f7f49193ccc90b`.

| Dataset | Route | Scanned | In scope | Accepted | Quarantined |
|---|---|---:|---:|---:|---:|
| Well registry | ArcGIS `Wells_Public` | 681 | 681 | 681 | 0 |
| Well history | FTP `wellhistory.zip` | 322,744 | 1,102 | 1,098 | 4 |
| Production | FTP `wcproduction.zip` | 48,412,089 | 36,754 | 36,754 | 0 |

**Selection:** Eddy County, type Gas, townships 23S-28E and 24S-28E, every status. The production window starts 2023-12.

| Raw file | Size (bytes) | SHA-256 |
|---|---:|---|
| `wcproduction.zip` | 974,763,778 | `ae1c65569357cee1c87e1fb77dbf5bcc444cb5f438fb2f58fa376d94b411824a` |
| `wellhistory.zip` | 44,318,403 | `4e157259fca2f33390f58161b8c8dc450a0ef42d0a0fdc22fab144f469fe8810` |
| `OCD Interface v1.1 Data Dictionary.xlsx` | 30,513 | `eae1cd092e34e84fc9021c533652165c85e2e901705f7fcabb352244eec1eb52` |
| `arcgis/page_000000.json` | 734,231 | `d997cbbc0c9d72c5ab05ce57791e4daeca051b63261ce43baece1aa1ecd95e58` |
| `arcgis/layer_metadata.json` | 14,349 | `ee63fd25ee8a4daf8505c9957686d3a9499109be124dafbdd7e22c346db4983b` |

OCD publishes no checksums, so these prove only that files are unchanged since receipt.

## Petrobras 3W

Batch `petrobras_3w-2.0.0-8aaa303f9b-7bf6887631`. Dataset 2.0.0 at commit `8aaa303f9b9d6ced690d136218d141624b10558d`. Aggregate checksum `d3f2463e3aa75eda128b0e355902fd62203b6b37ddfbefbc4e8b5069f3fb1fa2`.

498 of 2,228 instances, 28,226,175 observations, from 40 real wells. 503 of 504 stored files matched their Git blob hash from the pinned tree. The 504th is `tree.json`, the listing that supplies those hashes.

| Class | Event | Real | Simulated | Hand-drawn |
|---:|---|---:|---:|---:|
| 0 | Normal | 100 | 0 | 0 |
| 1 | Abrupt increase of BSW | 4 | 20 | 10 |
| 2 | Spurious closure of DHSV | 22 | 16 | 0 |
| 3 | Severe slugging | 32 | 20 | 0 |
| 4 | Flow instability | 60 | 0 | 0 |
| 5 | Rapid productivity loss | 11 | 20 | 0 |
| 6 | Quick restriction in PCK | 6 | 20 | 0 |
| 7 | Scaling in PCK | 36 | 0 | 10 |
| 8 | Hydrate in production line | 14 | 20 | 0 |
| 9 | Hydrate in service line | 57 | 20 | 0 |
| | **Total** | **342** | **136** | **20** |

Classes 0 and 4 are capped subsets of 594 and 343 real instances. Simulated instances are capped at 20 per class.
