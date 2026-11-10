# pipelines/acquire/naip

USDA NAIP windows around selected registry wells, read from cloud-optimized GeoTIFFs through Planetary Computer.
Run with `make acquire-naip`, which runs the plume association first because it chooses the wells. Chips are
context imagery only. Their license for 2022 imagery is unconfirmed, so they are never committed.
