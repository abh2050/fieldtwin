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

12. An application connects as `fieldtwin_app`, never as the owner or a superuser (ADR 0015).
13. Aerial evidence is proximity and coverage only. Displayed text comes from fixed templates checked by `packages/inspection/claims.py`, a pattern backstop rather than a semantic check, so never display free text as evidence. Compare plumes with a null drawn inside their own scene footprints, not with the whole map. Reviews are blind and hold vocabulary values only. Real evidence never names an AETHER asset, inspection requests target fictional assets only, and no review is ever invented (ADR 0018).
14. Carbon Mapper data is non-commercial with attribution, and NAIP licensing for 2022 imagery is unconfirmed. Don't commit raw aerial data or NAIP pixels, and keep per-well evidence pages under `data/`.
15. Decisions use only operator-visible inputs, never simulator truth. A score is a sum of named terms and never a failure probability. Only a person approves; scripted demonstration actors are labelled `SCRIPTED_DEMO` and never counted as human. Economic outputs are modeled estimates for a fictional facility (ADR 0019).

Detection rules are fixed in `config/experiments/` before fitting. Read a holdout only after committing the development selection, and never pool 3W and AETHER results (ADR 0017).

Physical connectivity lives in `physical_nodes` and `physical_edges`, separate from evidence and identity. The field model is a simplified simulator, never a validated one (ADR 0016).

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
