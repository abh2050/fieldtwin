# Rules for agents and contributors

AETHER Field does not exist. Its operational relationships are fictional, while selected data comes from real public sources. Keep that distinction from ingestion through display.

## Data integrity

1. Never imply that one source was measured at another source's asset. 3W is offshore data. OCD describes real New Mexico wells. Neither was measured at AETHER Field.
2. Never replace a failed real-data acquisition with generated or alternate data. Report the failure instead.
3. Keep original identifiers, units, reporting grain, and quality flags. Treat unknown values as unknown, and a missing value is not zero.
4. Never allocate production across grains without a documented method.
5. Never promote `EMISSION_NEAR` to `SOURCE_ATTRIBUTED_TO`, and never treat replayed data as live.
6. Do not merge wells by name similarity. OCD identity uses the API number.
7. Raw data is immutable. Fix problems in later layers and send invalid records to quarantine with a reason.
8. Keep real and fictional assets in their own tables. Add a new sensor mapping only within one equipment class.
9. 3W is a separate offshore benchmark. Never map it onto AETHER assets (ADR 0014). AETHER telemetry is synthetic, and the simulator is not calibrated to any real well (ADR 0012).
10. Don't commit real OCD rows or name individual OCD wells in published files. OCD states no redistribution terms (ADR 0011).
11. Record reconciliation outcomes as decisions. Never turn an inferred association into a verified one automatically (ADR 0013).

## Claims

1. Do not report a gate, test, or benchmark as passed without executed evidence.
2. Do not hardcode success responses, and do not swallow exceptions.
3. Label modeled and estimated figures as such.

## Safety and cost

1. Nothing here may connect to or operate physical equipment. Recommendations stay advisory.
2. Do not create billable AWS resources without explicit approval. Read the AWS profile and region from configuration, and do not hardcode account IDs or credentials.
3. Bedrock, if ever enabled, only explains. It holds no decision or approval authority.

## Scope

Work proceeds gate by gate as defined in section 18 of `docs/specification.md`. Add a dependency in the gate that needs it. Record significant decisions as ADRs in `docs/adr/`.
