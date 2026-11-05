# ADR 0004: Stream OCD XML out of the zip instead of extracting it

**Status:** Accepted and implemented.

## Context

OCD exports are UTF-16 XML. `wellhistory.xml` is 44 MB zipped and 903 MB unzipped, about 20:1. `wcproduction.zip` is 975 MB, so at a similar ratio its XML is roughly 20 GB. The development machine had 28 GB free.

## Decision

Keep the original zip as the immutable raw record. Decompress and parse in one stream with `expat`, keep only target wells inside the time window, and write those rows to Parquet as original text.

## Consequences

- Peak disk use stays near the zip size, and memory stays bounded.
- A scan is single-threaded and must read the whole file, because the source order cannot be relied on.
- Truncated archives and malformed XML raise an error rather than yielding a partial result that looks complete.
- Changing the selected wells or window means scanning again, without a new download.
