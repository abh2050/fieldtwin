# FieldTwin technical specification

The full product and engineering specification. `instructions.md` is the short entry point for contributors and agents.

Revisions are recorded in `docs/adr/`. In particular, ADRs 0010, 0012, and 0014 define AETHER-FAULT-001 and keep Petrobras 3W separate from AETHER Field.

---

# 0. PROJECT DEFINITION

**FieldTwin** is an industrial asset intelligence and inspection decision-support platform.

**The industrial environment is named AETHER Field. AETHER Field is entirely fictional.**

AETHER Field is a hypothetical natural-gas production field modeled on the operating characteristics of distributed upstream oil-and-gas infrastructure in the Permian Basin.

The fictional facility comprises:

- 2 well pads, A and B.
- 6 natural-gas-producing wells per pad, for 12 total.
- Wellhead instrumentation, valves, and associated production equipment.
- A fictional gathering network connecting the wells to shared processing and compression equipment.
- A compression station containing 4 modeled compressor units.
- An equipment maintenance team responsible for inspections and repairs.
- An aerial inspection capability using drone-style observations.
- A hypothetical SCADA monitoring environment.
- A field operations center responsible for maintenance and inspection decisions.

The facility's layout, equipment relationships, maintenance history, sensor-to-asset assignments, and operational scenarios are fictional unless explicitly documented otherwise.

### Critical scientific integrity requirement

FieldTwin combines data from multiple independent public sources:

1. New Mexico Oil Conservation Division — actual well locations, identifiers, operator records, production data, and available inspection data.
2. Petrobras 3W — historical offshore well sensor measurements and labeled undesirable operating events, including real and simulated source instances.
3. Carbon Mapper — actual methane observations, geospatial emissions data, and related imagery.
4. USDA NAIP — actual georeferenced aerial photography.
5. Explicitly generated synthetic data — fictional equipment hierarchies, operational events, maintenance records, inspections, financial assumptions, and experimental relationships.

**These datasets do not describe the same real industrial facility.**

Never imply that Petrobras telemetry was measured at a New Mexico well, or that a Carbon Mapper observation establishes a methane leak at a fictional AETHER Field asset.

The purpose of this project is to demonstrate how a production-grade industrial data architecture could integrate heterogeneous data sources when properly associated with an operating environment.

All experimental associations must be explicit, reproducible, and traceable.

Distinguish:

- `OBSERVED`: An original source measurement or record, tied to its actual source.
- `DERIVED`: A computed feature from identified underlying records.
- `REPLAYED`: An existing source sequence used in an experimental scenario.
- `SYNTHETIC`: Generated values, assets, events, or relationships.
- `INFERRED`: A tentative association requiring supporting evidence and confidence assessment.

Keep source provenance separate from scenario assignment. A replayed measurement retains its original source origin.

Every screen that displays integrated experimental evidence must clearly indicate that AETHER Field is hypothetical.

### Product goal

Build a functional, end-to-end platform demonstrating:

**Asset registry → data acquisition → canonical data modeling → provenance-aware reconciliation → telemetry processing → fault detection → aerial inspection evidence → operational decision support → human approval → maintenance tracking → outcome analysis.**

This must be a working application rather than a UI-only mockup.

No fabricated benchmark results, fake deployment screenshots, simulated cloud-operation claims, or hardcoded success responses.

Actual synthetic test data is permitted when clearly marked.

---

# 1. IMPLEMENTATION MISSION

Build FieldTwin from an empty repository through a fully tested and demonstrable application.

The final system must:

1. Retrieve genuine public industrial datasets where technically and legally permitted.
2. Preserve raw source data.
3. Profile and validate each dataset.
4. Normalize information into a common industrial semantic model.
5. Resolve real-world identities only when supported by evidence.
6. Define the fictional AETHER Field asset hierarchy.
7. Keep experimental scenarios explicit, reproducible, and separate from source records.
8. Generate deterministic, physically constrained synthetic telemetry for AETHER Field, and keep source telemetry as an independent benchmark.
9. Detect operational anomalies using evaluated algorithms.
10. Display aerial inspection evidence and geospatial observations.
11. Generate physically and economically interpretable inspection priorities.
12. Support operator-reviewed maintenance recommendations.
13. Track work orders, approvals, simulated outcomes, and audit events.
14. Provide a web-based industrial operations dashboard.
15. Deploy the application to AWS.
16. Create complete technical documentation and a reproducible demonstration.

Do not attempt to implement everything simultaneously.

Use incremental, aspect-driven development with mandatory validation gates.

---

# 2. PRODUCT USERS AND USE CASES

## User personas

### Field Operator

Monitors wells and equipment, reviews abnormalities, creates inspection requests, and checks operational status.

### Reliability Engineer

Analyzes historical operating patterns, failure events, equipment risks, and maintenance recommendations.

### Maintenance Supervisor

Reviews work orders, approves maintenance actions, assigns resources, and tracks maintenance outcomes.

### Technical Reviewer

Audits model performance, source lineage, data transformations, assumptions, safety controls, and system behavior.

## Core use cases

### UC-01: Asset overview

Display the fictional production field, including wells, well pads, gathering equipment, and compression assets.

### UC-02: Production context

Display actual production records in their original reporting context, or explicitly transformed production profiles within a fictional scenario.

Do not display aggregated lease-level production as measured well-level output without documented allocation rules.

### UC-03: Fault detection

Detect anomalies in AETHER Field's synthetic telemetry, compared against the known synthetic fault onset.

Evaluate detection methods on the Petrobras 3W offshore benchmark separately, against its source labels. Results from one domain are not evidence about the other.

### UC-04: Aerial inspection

Associate georeferenced imagery with covered locations and display methane emission observations.

Distinguish spatial proximity from confirmed source attribution.

Allow an operator to review an image and record an inspection finding.

### UC-05: Maintenance prioritization

Generate maintenance recommendations using transparent rules and calibrated risk estimates where available.

Factor in severity, asset criticality, confidence, response cost, travel distance, and operating constraints.

### UC-06: Human-approved work orders

Create recommended work orders and allow authorized users to approve, reject, or request additional evidence.

### UC-07: Scenario comparison

Compare baseline and risk-based inspection schedules under documented assumptions.

All hypothetical savings must be identified as modeled estimates.

### UC-08: Evidence audit

For every recommendation, show:

- Source records.
- Transformations.
- Relevant asset and scenario mappings.
- Model version.
- Prediction or rule output.
- Assumptions.
- Human decision.
- Outcome.

---

# 3. TECHNOLOGY STACK

Use the following technologies as the initial architecture.

| Layer                      | Technology                                                  |
| -------------------------- | ----------------------------------------------------------- |
| Programming language       | Python 3.12+                                                |
| Frontend                   | React, TypeScript, Vite                                     |
| UI components              | Tailwind CSS, shadcn/ui                                     |
| Maps                       | MapLibre GL JS                                              |
| Charts                     | Apache ECharts                                              |
| Backend API                | FastAPI, Pydantic v2                                        |
| Local operational database | PostgreSQL 16 + PostGIS                                     |
| Cloud operational storage  | DynamoDB                                                    |
| Raw and curated data       | Amazon S3, Apache Parquet                                   |
| Analytical processing      | DuckDB, PyArrow                                             |
| Geospatial processing      | GeoPandas, Shapely, PyProj                                  |
| Dataset validation         | Pandera, pytest                                             |
| Industrial modeling        | NumPy, SciPy                                                |
| Machine learning           | scikit-learn, optional XGBoost                              |
| Experiment tracking        | MLflow, local artifact store first                          |
| Inference runtime          | Python CPU-based inference                                  |
| Optimization               | Google OR-Tools                                             |
| Cloud infrastructure       | AWS CDK v2, TypeScript                                      |
| API deployment             | AWS Lambda + API Gateway HTTP API                           |
| Frontend hosting           | Amazon S3 + CloudFront                                      |
| Authentication             | Amazon Cognito                                              |
| Secrets and encryption     | AWS Secrets Manager where needed, KMS/S3 managed encryption |
| Monitoring                 | CloudWatch structured logs and alarms                       |
| CI/CD                      | GitHub Actions                                              |
| Containerization           | Docker and Docker Compose                                   |
| Documentation              | Markdown, draw\.io, Mermaid                                 |
| Optional AI explanation    | Amazon Bedrock, disabled by default                         |

Do not introduce Kubernetes, SageMaker endpoints, Amazon Neptune, OpenSearch, or a managed vector database in the MVP.

They are not necessary to demonstrate the business problem and would introduce operational cost and complexity.

## Local/cloud storage architecture

Develop against PostgreSQL/PostGIS locally because it supports relational integrity and sophisticated spatial queries.

For the low-cost AWS MVP, publish normalized asset records and bounded query views into DynamoDB, while retaining analytical Parquet files in S3.

Implement explicit repository interfaces:

- `AssetRepository`
- `ObservationRepository`
- `RelationshipRepository`
- `ScenarioRepository`
- `WorkOrderRepository`
- `AuditRepository`

Provide local PostgreSQL and cloud DynamoDB implementations where needed.

Do not assume SQL queries can be translated automatically into DynamoDB queries.

Design cloud access patterns intentionally, including required keys, indexes, pagination, conditional writes, and eventual-consistency behavior.

Do not use DynamoDB scans as the default implementation for every query.

Preserve SQL DDL and the complete canonical schema in the repository, even when the cloud API uses materialized DynamoDB views.

---

# 4. AWS DEPLOYMENT REQUIREMENTS

## AWS environment

Configure these through environment variables. Do not commit developer-specific values.

- AWS CLI profile: `AWS_PROFILE`.
- AWS region: `AWS_REGION`, a single regional deployment target.
- Environment: `dev`.
- Project identifier: `fieldtwin-aether`.

Do not hardcode AWS account numbers, access keys, credentials, or secret values into the codebase.

Discover the current account ID dynamically using AWS STS.

Before provisioning any service, verify that it is available and permitted in the target account and region, including any organizational policies.

Do not assume access to all Bedrock models.

If Bedrock is used, enumerate available inference profiles in the configured region and verify access first.

## Default AWS architecture

### Frontend

React/Vite application → private S3 bucket → CloudFront Origin Access Control → HTTPS user access.

### API

CloudFront frontend → API Gateway HTTP API → Lambda-hosted FastAPI application through Mangum.

### Operational storage

DynamoDB tables for asset read models, observation metadata, verified relationships, scenarios, work orders, and audit events.

### Analytical storage

S3 buckets or prefixes for immutable raw records, normalized Parquet, generated features, model artifacts, imagery, and reproducible experiment outputs.

### Data processing

Run acquisition, profiling, model training, and large normalization jobs locally first.

Publish validated artifacts to S3 only after successful gate checks.

For cloud batch processing, provide an optional short-lived ECS Fargate task definition. Do not continuously operate ECS infrastructure.

### Event processing

Use SQS where asynchronous processing materially improves reliability.

Use local replay initially. Implement cloud replay as an optional bounded, rate-limited batch.

### Authentication

Use Cognito user authentication for private application access.

Roles:

- Viewer.
- Operator.
- Maintenance Supervisor.
- Admin.

Enforce authorization on the backend, not just in the frontend.

### Logging

Use JSON structured logging with correlation IDs, scenario IDs, ingestion batch IDs, and model version references.

Never log credentials or sensitive tokens.

### Cost controls

Target a maximum experimental cloud budget of $150 per month.

Before deployment:

1. Inspect existing infrastructure and account permissions.
2. Generate an infrastructure diff.
3. Produce a conservative cost estimate with explicit usage assumptions.
4. Identify recurring versus usage-based costs.
5. Configure budget alerts where authorized.
6. Require explicit approval before creating billable resources.

Avoid NAT Gateways, permanent Fargate services, always-on load balancers, and managed database instances unless justified and explicitly approved.

Support deployment shutdown and complete resource teardown.

Retain source manifests and reproducibility documentation when infrastructure is destroyed.

Create:

- `make aws-plan`
- `make aws-deploy`
- `make aws-smoke-test`
- `make aws-stop`
- `make aws-destroy`

Do not automatically destroy unrelated AWS resources.

The first deployment should be private and authenticated.

---

# 5. DATA SOURCES — REQUIRED ACQUISITION WORK

Do not invent dataset contents.

Inspect official source documentation, verify current download endpoints, and create adapters for actual source schemas.

## Source 1: New Mexico Oil Conservation Division

Official reference:

[https://www.emnrd.nm.gov/ocd/ocd-data/](https://www.emnrd.nm.gov/ocd/ocd-data/)

Acquire a bounded representative set of wells in a compact production region, with available identifiers, coordinates, production associations, and operating statuses.

Target:

- 500–1,000 well records if available.
- 24–36 months of compatible production history.
- Operator and lease associations where published.
- Available inspection history where accessible.

Preserve actual reporting grain and original units.

Capture source-specific identifiers and production reporting relationships.

Do not allocate lease production to individual wells without explicitly documenting the allocation methodology.

## Source 2: Petrobras 3W

Official repository:

[https://github.com/petrobras/3W](https://github.com/petrobras/3W)

Inspect:

- Dataset documentation.
- Dataset version.
- `dataset.ini`.
- Parquet structure.
- Source category labels.
- Event label definitions.
- Units.
- Sampling frequencies.
- Missing-value behavior.
- Licensing and attribution requirements.

Download a representative bounded subset before attempting the complete dataset.

Target initially:

- Normal operating periods.
- Multiple undesirable event classes.
- Real source examples.
- Separately identified originally simulated examples.
- Enough events for leakage-safe model evaluation.

Do not infer that variables with similar names measure the same physical equipment point.

Maintain the actual source instance identifier through the pipeline.

## Source 3: Carbon Mapper

Official API:

[https://api.carbonmapper.org/api/v1/docs](https://api.carbonmapper.org/api/v1/docs)

Acquire a small research dataset of available methane plume observations.

Record:

- Observation identifier.
- Observation timestamp.
- Geographic location.
- Available emission estimate.
- Uncertainty.
- Instrument and acquisition metadata.
- Source classification where present.
- Image or plume geometry references.
- Data usage and attribution restrictions.

Observe API rate limits and licensing.

Do not infer that a plume was caused by the nearest well.

Do not represent aerial remote-sensing observations as drone-mounted camera measurements.

## Source 4: USDA NAIP

Acquire georeferenced aerial imagery for a small set of real well locations.

Preserve:

- Acquisition date.
- Ground sampling distance.
- Coordinate reference system.
- Image footprint.
- Original image source.
- Data usage terms.

NAIP imagery is for facility context and geospatial visualization.

Do not claim that it provides validated leak labels or equipment-defect labels.

## Source 5: AETHER synthetic operational records

Generate fictional:

- Asset hierarchy.
- Equipment connectivity.
- Facility topology.
- Example sensor-to-equipment assignments.
- Inspection missions.
- Inspection outcomes.
- Maintenance work orders.
- Technician routes.
- Work schedules.
- Estimated repair durations.
- Economic assumptions.
- Operating scenarios.

Use deterministic random seeds.

Save the generation configuration and all assumptions.

Provide clear labels identifying synthetic records.

If actual data cannot be retrieved, log the failure and produce a clear acquisition report.

A previously captured, source-verified local fixture may be used offline.

Never silently substitute newly generated data for a failed real-data acquisition.

---

# 6. CANONICAL INDUSTRIAL DATA MODEL

Create normalized SQL DDL, migrations, Pydantic schemas, and data dictionaries.

## Core entities

### `facilities`

Fields:

- facility_id
- facility_name
- facility_type
- region
- is_fictional
- geometry
- created_at

AETHER Field must always have `is_fictional = true`.

### `assets`

- asset_id
- facility_id
- parent_asset_id
- asset_type
- asset_name
- equipment_class
- operating_status
- geometry
- is_fictional
- created_at

Support a hierarchical asset relationship model.

### `source_systems`

- source_system_id
- provider
- source_url
- source_version
- license
- retrieval_timestamp
- usage_constraints

### `ingestion_batches`

- batch_id
- source_system_id
- ingestion_timestamp
- original_checksum
- source_record_count
- accepted_count
- rejected_count
- processing_status
- manifest_uri

### `source_identifiers`

- identifier_id
- source_system_id
- canonical_asset_id
- external_identifier
- identifier_type
- valid_from
- valid_to
- verification_status

Canonical identifiers may be nullable where an authoritative asset association cannot be established.

### `observations`

- observation_id
- source_system_id
- source_record_id
- timestamp
- observation_type
- metric_name
- numeric_value
- unit
- quality_flag
- geometry
- provenance_class
- original_record_uri

Store high-volume sensor values in partitioned Parquet while preserving queryable metadata.

### `sensor_tags`

- tag_id
- source_system_id
- native_tag_name
- canonical_metric
- equipment_position
- unit
- pressure_reference_type
- sampling_frequency
- mapping_status

### `asset_observation_links`

- link_id
- asset_id
- observation_id
- relationship_type
- evidence_reference
- confidence
- verification_status
- method_version

Allowed relationship types include:

- `MEASURED_AT`
- `IMAGE_COVERS`
- `EMISSION_NEAR`
- `SOURCE_ATTRIBUTED_TO`
- `ASSOCIATED_WITH`
- `EXPERIMENTAL_SCENARIO_LINK`

Never automatically promote an `EMISSION_NEAR` relationship to `SOURCE_ATTRIBUTED_TO`.

### `asset_relationships`

- relationship_id
- source_asset_id
- target_asset_id
- relationship_type
- evidence_type
- provenance_class
- effective_from
- effective_to

### `production_records`

- record_id
- source_system_id
- reporting_entity_id
- reporting_grain
- reporting_period
- oil_volume
- gas_volume
- water_volume
- unit_system
- original_record_uri

Support well, lease, operator, and other source-specific reporting grains without confusing them.

### `telemetry_events`

- event_id
- source_instance_id
- source_event_class
- start_timestamp
- end_timestamp
- real_or_simulated_source
- parquet_uri
- dataset_version

### `scenarios`

- scenario_id
- scenario_name
- scenario_description
- target_facility_id
- scenario_version
- random_seed
- created_at

### `scenario_mappings`

- mapping_id
- scenario_id
- target_asset_id
- original_source_instance_id
- transformation_config
- compatibility_assessment
- mapping_provenance
- replay_start_time

A scenario mapping must never overwrite the original source identity.

### `inspection_observations`

- inspection_id
- observation_id
- inspection_type
- asset_candidate_id
- evidence_uri
- finding
- reviewer
- confidence
- review_status

### `anomaly_predictions`

- prediction_id
- scenario_id
- source_event_id
- model_version
- event_timestamp
- predicted_class
- anomaly_score
- decision_threshold
- evidence_reference

### `work_orders`

- work_order_id
- scenario_id
- asset_id
- recommended_action
- severity
- priority
- status
- estimated_cost
- evidence_reference
- created_at

### `approval_events`

- approval_id
- work_order_id
- actor_id
- action
- justification
- timestamp

### `audit_events`

- event_id
- actor_id
- operation
- target_id
- timestamp
- correlation_id
- before_state_reference
- after_state_reference

## Integrity requirements

Implement foreign keys, check constraints, unique indexes, and appropriate geospatial indexes in PostgreSQL.

For cloud DynamoDB read models, preserve equivalent invariants in validated application logic and conditional writes.

Every observation must retain source lineage.

Every scenario association must be distinguishable from a confirmed real-world relationship.

Every operational action must be linked to supporting evidence.

---

# 7. DATA ENGINEERING ARCHITECTURE

Implement a layered data platform.

## Raw

Immutable original records:

`data/raw/<source>/<version>/<batch_id>/`

Store original payloads, schema metadata, licenses, and checksums.

## Bronze

Parsed source-specific records with original semantics retained.

No premature cross-source joins.

## Silver

Normalized canonical records, standardized time formats, verified units, resolved identifiers, and validated geometries.

Preserve original measurement definitions and quality flags.

## Gold

Purpose-built analytical datasets:

- Asset inventory.
- Production history.
- Sensor event windows.
- Geospatial inspection coverage.
- Emission proximity candidates.
- Anomaly features.
- Scenario replay features.
- Maintenance priority views.
- Economic comparison outputs.

Each Gold dataset must declare whether it is observed, derived, or experimental.

## Pipeline requirements

Use:

- Python.
- DuckDB.
- PyArrow.
- Pandera.
- GeoPandas.
- Structured JSON logging.

Support incremental acquisition, retryable downloads, bounded concurrency, idempotent processing, and checkpointing.

Create a manifest for every ingestion batch.

Use explicit quarantine for invalid records.

Do not drop invalid records silently.

Produce quality reports including:

- Record counts.
- Schema violations.
- Missing fields.
- Duplicate identifiers.
- Geospatial validity.
- Timestamp anomalies.
- Unit conversion issues.
- Unresolved asset relationships.
- Source-to-target mapping coverage.

---

# 8. DATA RECONCILIATION ENGINE

Create a dedicated reconciliation module.

The module must support four distinct processes.

## A. Identity reconciliation

Resolve real asset identities using authoritative identifiers and documented crosswalks.

Do not merge wells using name similarity alone.

## B. Geospatial association

Calculate geospatial relationships using valid coordinate systems and appropriate physical distance metrics.

Include observation footprints and uncertainty where available.

An emission near an asset is a candidate association, not confirmed source attribution.

## C. Semantic normalization

Normalize metric names, equipment positions, time units, physical units, and event labels.

Reject or flag ambiguous sensor definitions.

For pressure measurements, distinguish absolute, gauge, and differential reference types.

## D. Experimental scenario mapping

AETHER Field scenarios use synthetic telemetry generated by a documented physical model. Petrobras 3W stays an independent offshore benchmark and is not mapped onto fictional assets.

Any experimental association must be explicit, versioned, immutable, and distinguishable from a verified relationship.

Validate equipment and operating-condition compatibility, and reject physically implausible mappings.

Create automated tests that prove:

1. Real observation identities remain intact.
2. Simulated mappings cannot create authoritative real-world measurement relationships.
3. Invalid semantic conversions are rejected.
4. Missing evidence does not produce a fabricated confidence value.
5. Downstream decision APIs preserve evidence classifications.

---

# 9. FICTIONAL FACILITY MODEL

Construct AETHER Field as a reproducible fictional asset hierarchy.

Required hierarchy:

```
AETHER Field
|
+-- Well Pad A
|   +-- Well A-01
|   +-- Well A-02
|   +-- Well A-03
|   +-- Well A-04
|   +-- Well A-05
|   +-- Well A-06
|
+-- Well Pad B
|   +-- Well B-01
|   +-- Well B-02
|   +-- Well B-03
|   +-- Well B-04
|   +-- Well B-05
|   +-- Well B-06
|
+-- Gathering Network
|   +-- Gathering Segments
|   +-- Isolation Valves
|
+-- Compression Station
|   +-- Compressor C-01
|   +-- Compressor C-02
|   +-- Compressor C-03
|   +-- Compressor C-04
|
+-- Field Operations
    +-- Inspection Missions
    +-- Maintenance Resources
    +-- Work Orders
```

All geometry should be generated using a declared geographic reference and physically reasonable facility spacing.

Use an intentionally fictional layout. Do not invent a real company's facility and present it as its actual infrastructure.

Define equipment relationships and simplified process assumptions in machine-readable configuration.

Create an asset topology diagram and a geographic representation.

---

# 10. TELEMETRY AND MACHINE LEARNING

## Initial detection approaches

Implement three benchmark approaches:

1. Transparent threshold/rule baseline.
2. Statistical anomaly detection.
3. Supervised classification using suitable labeled events.

Choose the final algorithms based on actual data inspection.

Do not assume every dataset supports every modeling approach.

Use training/validation/test partitions that prevent leakage between correlated windows from the same source event.

Prefer grouping by original source instance and, where supported, actual well identity.

## Evaluation

Measure:

- Precision.
- Recall.
- F1.
- False alarms.
- Detection delay.
- Confusion matrix.
- Performance by event class.
- Performance under missing sensor values.
- Inference latency.
- CPU and memory usage.

Record exact dataset version, split definitions, thresholds, random seeds, hardware environment, and artifact checksums.

Do not fabricate model performance.

Store experiment results with MLflow.

Export selected models to portable CPU-compatible artifacts.

## Runtime

Implement deterministic replay of synthetic AETHER telemetry and, separately, of benchmark instances.

Support:

- Play.
- Pause.
- Reset.
- Replay speed adjustment.
- Fault scenarios defined by the synthetic model.
- Model inference.
- Event detection.
- Evidence generation.

Live operational telemetry is not required.

Clearly indicate that replayed and simulated data is experimental.

---

# 11. AERIAL INSPECTION MODULE

The first version is an inspection evidence and prioritization system.

It is not an autonomous drone flight controller.

Implement:

- Georeferenced imagery display.
- Observation footprints.
- Image inspection metadata.
- Spatial proximity analysis.
- Emission observation overlays.
- Evidence review.
- Human annotation.
- Inspection findings.
- Inspection request generation.

If verified equipment-defect imagery is unavailable, do not claim trained visual defect detection.

Instead, implement the complete workflow for ingesting imagery, associating it with spatial coverage, and recording reviewed findings.

Optional computer vision may be added only with suitable licensed, labeled data and valid evaluation.

Do not control real aircraft or industrial equipment.

---

# 12. OPERATIONAL DECISION ENGINE

The decision engine must be deterministic and transparent by default.

Possible inputs:

- Anomaly evidence.
- Equipment criticality.
- Source confidence.
- Inspection history.
- Maintenance status.
- Estimated travel cost.
- Repair cost assumptions.
- Failure consequence estimates.
- Personnel availability.

Compute a documented maintenance priority score or optimization objective.

Avoid treating uncalibrated ML scores as actual failure probabilities.

Provide explanations for every recommendation.

Implement optional route optimization using OR-Tools.

Compare:

- Fixed inspection scheduling.
- Risk-based inspection scheduling.
- Route-optimized maintenance scheduling.

Expose costs and assumptions.

All economic outputs are modeled scenario estimates, not realized customer savings.

No automatic industrial actuation is permitted.

Require operator approval for work-order progression.

Use explicit state transitions and audit events.

---

# 13. OPTIONAL GENERATIVE AI

Generative AI is not the control authority.

Use Amazon Bedrock only as an optional explanation service.

Potential uses:

- Summarize an anomaly investigation.
- Explain the evidence behind an inspection recommendation.
- Summarize maintenance history.
- Produce a cited operator briefing.

Rules:

1. No direct LLM control of equipment.
2. No LLM authority to approve work orders.
3. No invented telemetry values.
4. No invented manuals or source citations.
5. Deterministic rules must produce the final decision state.
6. If Bedrock is unavailable, the product remains fully functional.
7. Log model identifiers and inference costs where applicable.
8. Minimize sensitive data sent to model endpoints.

Do not introduce a vector database until retrieval requirements justify one.

---

# 14. FRONTEND APPLICATION

Build a professional industrial operations dashboard.

Use React, TypeScript, Tailwind, shadcn/ui, MapLibre, and ECharts.

Required navigation:

### Overview

Facility health, scenario status, active anomalies, pending inspections, maintenance backlog, and modeled economics.

### Field Map

Interactive fictional facility map, well pads, wells, shared equipment, imagery, and geospatial observations.

### Asset Explorer

Asset hierarchy, equipment details, operating history, source provenance, and relationships.

### Telemetry Lab

Interactive time-series charts, replay controls, anomaly detection overlays, and model evaluation summaries.

### Aerial Inspection

Inspection evidence, map overlays, imagery review, candidate source associations, and operator annotations.

### Decision Center

Risk prioritization, recommendations, explanations, and work-order actions.

### Maintenance

Work-order management, approval workflow, technician assignment, and route comparisons.

### Data Lineage

Source system inventory, ingestion runs, data quality, raw-to-curated lineage, and scenario mappings.

### Experiment Reports

Actual benchmark results, model comparison, reproducibility, compute performance, and costs.

## Visual design

Professional industrial SaaS design.

Use a restrained visual hierarchy, readable tables, and effective filtering.

Do not create decorative gauges that contain invented values.

Every metric must come from an actual backend calculation or a clearly disclosed synthetic scenario.

Every screen must contain an accessible fictional-facility disclosure.

Provide loading, empty, error, and degraded-service states.

---

# 15. API CONTRACTS

Use FastAPI and OpenAPI.

Required endpoint groups:

```
GET    /health
GET    /api/v1/facilities
GET    /api/v1/assets
GET    /api/v1/assets/{asset_id}
GET    /api/v1/assets/{asset_id}/relationships
GET    /api/v1/assets/{asset_id}/observations

GET    /api/v1/data-sources
GET    /api/v1/ingestion-runs
GET    /api/v1/data-quality
GET    /api/v1/lineage/{record_id}

GET    /api/v1/scenarios
POST   /api/v1/scenarios/{scenario_id}/replay
POST   /api/v1/scenarios/{scenario_id}/pause
POST   /api/v1/scenarios/{scenario_id}/reset

GET    /api/v1/anomalies
GET    /api/v1/anomalies/{event_id}
GET    /api/v1/model-evaluations

GET    /api/v1/inspections
GET    /api/v1/inspection-evidence/{id}

GET    /api/v1/recommendations
GET    /api/v1/work-orders
POST   /api/v1/work-orders
POST   /api/v1/work-orders/{id}/approve
POST   /api/v1/work-orders/{id}/reject

GET    /api/v1/economics/comparison
GET    /api/v1/audit-events
```

Implement authorization, validation, pagination, filters, structured errors, request correlation IDs, and idempotency where appropriate.

State-changing endpoints must require valid authentication and authorization.

Do not return fabricated successful operations.

---

# 16. REPOSITORY SCAFFOLD

Create this structure:

```
fieldtwin/
|
+-- README.md
+-- CLAUDE.md
+-- AGENTS.md
+-- Makefile
+-- pyproject.toml
+-- package.json
+-- .env.example
+-- .gitignore
+-- docker-compose.yml
|
+-- config/
|   +-- environments/
|   +-- facility/
|   |   +-- aether_field.yaml
|   +-- sources/
|   +-- scenarios/
|   +-- rules/
|
+-- data/
|   +-- raw/
|   +-- bronze/
|   +-- silver/
|   +-- gold/
|   +-- fixtures/
|   +-- manifests/
|
+-- data_contracts/
|   +-- sources/
|   +-- canonical/
|   +-- semantic_mappings/
|
+-- apps/
|   +-- web/
|   |   +-- src/
|   |   +-- public/
|   |   +-- tests/
|   +-- api/
|       +-- src/
|       +-- tests/
|
+-- packages/
|   +-- domain/
|   +-- repositories/
|   +-- provenance/
|   +-- reconciliation/
|   +-- scenario_engine/
|   +-- telemetry/
|   +-- anomaly_detection/
|   +-- inspection/
|   +-- decision_engine/
|   +-- optimization/
|
+-- pipelines/
|   +-- acquire/
|   |   +-- nm_ocd/
|   |   +-- petrobras_3w/
|   |   +-- carbon_mapper/
|   |   +-- naip/
|   +-- profile/
|   +-- normalize/
|   +-- reconcile/
|   +-- publish/
|   +-- synthetic/
|
+-- models/
|   +-- training/
|   +-- evaluation/
|   +-- artifacts/
|
+-- db/
|   +-- migrations/
|   +-- ddl/
|   +-- seeds/
|
+-- infra/
|   +-- cdk/
|   +-- policies/
|   +-- cost/
|
+-- tests/
|   +-- unit/
|   +-- integration/
|   +-- contract/
|   +-- e2e/
|   +-- security/
|   +-- performance/
|   +-- provenance/
|
+-- reports/
|   +-- ingestion/
|   +-- reconciliation/
|   +-- data_quality/
|   +-- experiments/
|   +-- economics/
|   +-- aws/
|   +-- gates/
|
+-- docs/
|   +-- index.html
|   +-- architecture/
|   +-- architecture.drawio
|   +-- adr/
|   +-- product/
|   +-- datasets/
|   +-- deployment/
|   +-- demos/
|
+-- scripts/
|   +-- bootstrap.sh
|   +-- validate.sh
|   +-- run_demo.sh
|   +-- aws_plan.sh
|   +-- aws_destroy.sh
|
+-- .github/
    +-- workflows/
```

Adapt the scaffold if necessary for sound engineering reasons, but document changes in an Architecture Decision Record.

The repository must be comprehensible to a technical reviewer.

---

# 17. ASPECT-DRIVEN DEVELOPMENT

Implement independent aspects rather than building the application as one large monolith.

Required aspects:

- A01 — Source acquisition and provenance.
- A02 — Canonical asset modeling.
- A03 — Entity and geospatial reconciliation.
- A04 — Experimental facility simulation.
- A05 — Telemetry processing.
- A06 — Anomaly detection.
- A07 — Aerial inspection evidence.
- A08 — Deterministic decision-making.
- A09 — Maintenance workflows.
- A10 — Web application.
- A11 — AWS infrastructure and security.
- A12 — Evaluation, documentation, and demonstrations.

For each aspect:

1. Write requirements.
2. Define interfaces.
3. Implement the smallest vertical slice.
4. Create tests.
5. Execute tests.
6. Record results.
7. Resolve failures.
8. Produce a completion report.
9. Proceed only after acceptance criteria pass.

Never claim a gate passed without execution evidence.

---

# 18. DEVELOPMENT GATES

> **Roadmap changed on 2026-11-10 ([ADR 0020](adr/0020-diagnostic-reset.md)).** Gates 0 to 4 are the foundation and Gates 5 to 7 are completed experimental evidence. Gates 8 to 10 below are **paused**. Diagnostic Milestone D1 ([specification](product/d1_diagnostic_spec.md)) comes next, before any UI or deployment work. The gate definitions below are kept as originally written.

## Gate 0 — Project foundation

Deliver:

- Repository scaffold.
- Product requirements.
- Architecture decision records.
- AWS cost and security plan.
- Initial draw\.io architecture.
- Developer instructions.
- Local bootstrap.

Acceptance:

A clean checkout successfully initializes the environment.

## Gate 1 — Source acquisition

Deliver:

- Working source adapters.
- Verified dataset URLs.
- Source manifests.
- Actual retrieved sample records.
- License inventory.
- Download failure handling.

Acceptance:

At least the primary registry and telemetry sources are acquired and independently validated.

Optional sources can be deferred with a documented reason.

## Gate 2 — Canonical data model

Deliver:

- SQL schema.
- Migrations.
- Pydantic contracts.
- Data dictionaries.
- Source mappings.
- Data quality tests.

Acceptance:

Representative source records normalize without losing source identity or original semantics.

## Gate 3 — Reconciliation

Deliver:

- Identifier matching.
- Geospatial association.
- Semantic mapping.
- Scenario relationship handling.
- Negative tests for invalid joins.

Acceptance:

Real identity relationships and experimental mappings remain unambiguously distinguishable.

## Gate 4 — Fictional facility

Deliver:

- AETHER asset hierarchy.
- Fictional topology.
- Geometries.
- Equipment configuration.
- Reproducible scenario generator.

Acceptance:

All assets and relationships validate against declared facility constraints.

## Gate 5 — Telemetry and anomaly models

Deliver:

- Event replay.
- Baseline detection.
- ML benchmark.
- Experiment artifacts.
- Leakage checks.
- Performance reports.

Acceptance:

Models are evaluated against held-out source events and produce reproducible metrics.

## Gate 6 — Aerial evidence

Deliver:

- Imagery ingestion.
- Spatial coverage.
- Emission observation associations.
- Inspection review.

Acceptance:

The application correctly displays evidence and does not make unsupported equipment-failure or emission-attribution claims.

## Gate 7 — Decision support

Deliver:

- Risk prioritization.
- Transparent rule engine.
- Work-order approval.
- Audit history.
- Economic comparison.

Acceptance:

A complete synthetic scenario event can generate an evidence-backed recommendation and approved simulated work order.

## Gate 8 — Application

Deliver:

- Operational frontend.
- Integrated API.
- Map.
- Telemetry dashboard.
- Inspection screen.
- Work-order workflow.
- Lineage browser.

Acceptance:

The full scenario runs locally from a clean checkout, without hardcoded application responses.

## Gate 9 — AWS deployment

Deliver:

- AWS CDK stacks.
- Authenticated application.
- Data publishing pipeline.
- Logging.
- Cost plan.
- Deployment and teardown scripts.

Acceptance:

Actual AWS smoke tests pass, with resource identifiers and evidence captured.

Do not deploy without explicit approval.

## Gate 10 — Portfolio demonstration

Deliver:

- Architecture diagrams.
- Reproducible walkthrough.
- Technical documentation.
- Model evaluation.
- Cost measurements.
- Security review.
- Known limitations.
- Demo video script.
- Production-hardening roadmap.

Acceptance:

A technical reviewer can run or inspect the product and distinguish measured outcomes from modeled assumptions.

---

# 19. TESTING AND RELIABILITY

Use pytest for backend tests and an appropriate frontend testing framework.

Include:

- Unit tests.
- Schema contract tests.
- Data quality tests.
- Reconciliation tests.
- End-to-end workflow tests.
- Role authorization tests.
- Replay determinism tests.
- API integration tests.
- Infrastructure checks.
- Deployment smoke tests.
- Teardown verification.

Test failure conditions:

- Missing or malformed source files.
- Duplicate well identifiers.
- Invalid coordinates.
- Wrong pressure units.
- Missing sensor values.
- Contradictory timestamps.
- Unverified methane attribution.
- Invalid source-to-scenario mapping.
- Unsupported equipment compatibility.
- Replayed or simulated observations treated as live measurements.
- Unauthorized work-order approval.
- Duplicate work-order submissions.
- ML inference failure.
- Bedrock unavailability.
- External API outage.

Use explicit failure states and recovery procedures.

Do not swallow exceptions or return artificial success objects.

---

# 20. SECURITY AND SAFETY

The application is a decision-support simulation.

It must never directly operate a physical well, valve, compressor, PLC, or SCADA endpoint.

Use:

- Least-privilege IAM.
- Cognito authentication.
- Server-side role enforcement.
- Private S3 data storage.
- Encryption in transit.
- Encryption at rest.
- Managed secret storage.
- Restricted CORS.
- Input validation.
- API throttling.
- Audit trails.
- Dependency scanning.
- Infrastructure security checks.

Avoid public raw-data buckets, hardcoded credentials, or unrestricted administrative APIs.

No genuine production equipment credentials or operationally sensitive private SCADA data are required.

All control recommendations must remain advisory.

---

# 21. DOCUMENTATION REQUIREMENTS

Documentation is a first-class deliverable.

Create a functional `docs/index.html` landing page suitable for GitHub Pages.

Include:

1. Executive product overview.
2. AETHER Field fictional facility disclosure.
3. Business problem.
4. System capabilities.
5. Architecture.
6. Source datasets and provenance.
7. Data reconciliation design.
8. Digital twin simulation.
9. Anomaly detection and model evaluation.
10. Decision engine.
11. AWS infrastructure.
12. Actual deployment cost and assumptions.
13. Testing results.
14. Demo walkthrough.
15. Known limitations.
16. Future extensions.

Create editable draw\.io architecture diagrams.

Required diagrams:

- System context.
- Fictional facility asset topology.
- Source-to-canonical data flow.
- Entity reconciliation and provenance.
- Telemetry event lifecycle.
- Decision and approval workflow.
- AWS deployment architecture.
- Security trust boundaries.

Maintain ADRs for significant technical decisions.

Do not present proposed results as measured outcomes.

Use clear, concise technical writing. Avoid promotional claims unsupported by implementation evidence.

---

# 22. REPRODUCIBLE DEMONSTRATION

Create one canonical end-to-end scenario.

Scenario name:

**AETHER-FAULT-001 — Progressive Gathering-Line Restriction**

A fictional natural-gas well experiences increasing flow resistance and downstream backpressure caused by a developing restriction in a gathering-line segment. Telemetry is synthetic and comes from a documented simplified physical model. It does not replay Petrobras 3W or any other source.

Expected workflow:

1. Select fictional Well A-03.
2. Initialize its synthetic operating conditions.
3. Produce baseline telemetry.
4. Introduce a progressively increasing restriction.
5. Generate correlated sensor observations.
6. Record the known synthetic fault onset.
7. Emit an anomaly event through the shared event contract.
8. Preserve the simulator parameters and reproducibility seed.
9. Prepare outputs for inspection prioritization and work-order workflows.
10. Generate a maintenance recommendation using transparent rules (Gate 7).
11. Compare the modeled inspection priority with other fictional assets (Gate 7).
12. Require operator approval, create the work order, and record the decision in the audit log (Gate 7).
13. Display modeled operational and economic outcomes, and the full chain of lineage (Gates 7 and 8).

Petrobras 3W remains an independent offshore benchmark. Do not map its events into fictional AETHER assets, and do not claim transfer of model accuracy between the two domains.

The demo must state:

> AETHER Field is a fictional industrial production environment. Its telemetry is synthetic and comes from a simplified physical model that is not calibrated to any real well. Public industrial datasets are used separately, in their own context.

Do not claim that the simulator is a calibrated representation of a real well.

---

# 23. FINAL DELIVERY CRITERIA

The project is complete only when:

- Actual public source data has been acquired and validated.
- Source licenses and usage restrictions are documented.
- Original records and source identifiers are preserved.
- Canonical schema migrations run successfully.
- Invalid cross-source associations are rejected.
- The fictional facility is reproducibly generated.
- A genuine labeled sensor benchmark has been evaluated.
- The inspection evidence workflow functions.
- The decision engine produces traceable recommendations.
- Human approvals and audit logging function.
- The complete application runs locally.
- The AWS deployment has been validated after authorization.
- Deployment costs and teardown are documented.
- Architecture diagrams are complete.
- `docs/index.html` functions.
- Automated tests pass.
- Actual benchmark outputs are saved under `reports/`.
- The demo can be reproduced without hidden manual steps.

---

# 24. IMPLEMENTATION BEHAVIOR

Follow these working rules:

1. Inspect the repository before making changes.
2. Establish architecture and requirements first.
3. Keep the implementation simple unless complexity is justified.
4. Use small, reviewable changes.
5. Prefer deterministic behavior for safety-sensitive decisions.
6. Preserve provenance at every transformation.
7. Treat unknown relationships as unknown.
8. Verify external dataset schemas before writing adapters.
9. Use real measurements for benchmark claims.
10. Use generated data only with explicit synthetic classification.
11. Record tests and actual outputs.
12. Do not claim completion without evidence.
13. Do not deploy billable AWS resources without approval.
14. Never exceed the agreed cloud spending boundary without approval.
15. Maintain a current implementation plan and gate status.
16. Update architecture diagrams when the implementation changes.
17. Produce a concise engineering report at the conclusion of each gate.

If a requirement conflicts with an AWS permission, data license, physical constraint, or documented source limitation, preserve the constraint, document the blocker, and choose the safest technically defensible alternative.

Do not hide limitations.

---

# 25. EXECUTION RECORD

Work proceeds gate by gate. Status and evidence for each gate are in `reports/gates/`, and significant decisions are in `docs/adr/`.

---

# FINAL PRINCIPLE

**FieldTwin is an industrial decision-support platform built around physical reality, explicit uncertainty, provenance-aware data integration, and reproducible engineering.**

**AETHER Field is a fictional facility used to demonstrate its capabilities.**

The purpose is to demonstrate the engineering practices necessary for a real industrial system without pretending that unrelated public datasets originated from the same operating facility.
