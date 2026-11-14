# Canonical schema

Generated from the PostgreSQL catalog by `make schema-docs`. A test fails if this file differs from a freshly migrated database.

50 tables and 9 views. DDL lives in [`db/migrations/`](../../db/migrations/), with a full dump in [`db/ddl/schema.sql`](../../db/ddl/schema.sql).

AETHER Field is fictional. Real source entities live in `source_assets` and fictional ones in `assets`, and no foreign key lets one stand in for the other.

## Enumerations

- `compatibility_class`: DIRECTLY_COMPATIBLE, CONDITIONALLY_COMPATIBLE, INCOMPATIBLE, INSUFFICIENT_EVIDENCE
- `instance_origin`: REAL, SIMULATED, HAND_DRAWN
- `provenance_class`: OBSERVED, DERIVED, REPLAYED, SYNTHETIC, INFERRED
- `reference_type`: ABSOLUTE, GAUGE, DIFFERENTIAL, UNKNOWN, NOT_APPLICABLE
- `spatial_status`: USABLE, QUARANTINED, UNRESOLVED_DATUM, NO_LOCATION
- `verification_status`: VERIFIED, UNVERIFIED, UNRESOLVED, REJECTED

## Tables

### `anomaly_predictions`

| Column | Type | Null | Description |
|---|---|---|---|
| `prediction_id` | bigint | no |  |
| `scenario_id` | text | yes |  |
| `source_event_id` | text | no |  |
| `model_version` | text | no |  |
| `event_timestamp` | timestamp without time zone | no |  |
| `predicted_class` | text | no |  |
| `anomaly_score` | double precision | yes |  |
| `decision_threshold` | double precision | yes |  |
| `evidence_reference` | text | no |  |
| `provenance_class` | provenance_class | no |  |

Check constraints: `anomaly_predictions_provenance_class_check`.
Keys: 1 primary key, 2 foreign key, 0 unique.

### `api_idempotency_keys`

Successful responses to state-changing requests, keyed by caller and Idempotency-Key.

| Column | Type | Null | Description |
|---|---|---|---|
| `actor_id` | text | no |  |
| `idempotency_key` | text | no |  |
| `method` | text | no |  |
| `path` | text | no |  |
| `request_sha256` | text | no |  |
| `status_code` | integer | no |  |
| `response` | jsonb | no |  |
| `created_at` | timestamp with time zone | no |  |

Check constraints: `api_idempotency_keys_idempotency_key_check`, `api_idempotency_keys_request_sha256_check`, `api_idempotency_keys_status_code_check`.
Keys: 1 primary key, 0 foreign key, 0 unique.

### `approval_events`

| Column | Type | Null | Description |
|---|---|---|---|
| `approval_id` | bigint | no |  |
| `work_order_id` | bigint | no |  |
| `actor_id` | text | no |  |
| `action` | text | no |  |
| `justification` | text | no |  |
| `timestamp` | timestamp with time zone | no |  |
| `actor_kind` | text | yes |  |
| `actor_role` | text | yes |  |

Check constraints: `approval_events_action_check`, `approval_events_actor_kind_check`.
Keys: 1 primary key, 1 foreign key, 0 unique.

### `asset_observation_links`

Links from observations to either a real or a fictional asset, never both.

| Column | Type | Null | Description |
|---|---|---|---|
| `link_id` | bigint | no |  |
| `source_asset_id` | text | yes |  |
| `asset_id` | text | yes |  |
| `observation_id` | bigint | no |  |
| `relationship_type` | text | no |  |
| `evidence_reference` | text | yes |  |
| `confidence` | double precision | yes |  |
| `verification_status` | verification_status | no |  |
| `method_version` | text | no |  |
| `provenance_class` | provenance_class | no |  |
| `scenario_id` | text | yes |  |

Check constraints: `asset_observation_links_confidence_check`, `asset_observation_links_relationship_type_check`, `attribution_needs_verified_evidence`, `confidence_needs_evidence`, `fictional_links_are_experimental`, `link_has_one_target`, `proximity_is_not_verified_attribution`, `real_links_are_not_experimental`.
Keys: 1 primary key, 4 foreign key, 0 unique.

### `asset_relationships`

Relationships between fictional assets. They can never be OBSERVED.

| Column | Type | Null | Description |
|---|---|---|---|
| `relationship_id` | bigint | no |  |
| `source_asset_id` | text | no |  |
| `target_asset_id` | text | no |  |
| `relationship_type` | text | no |  |
| `evidence_type` | text | no |  |
| `provenance_class` | provenance_class | no |  |
| `effective_from` | date | no |  |
| `effective_to` | date | yes |  |

Check constraints: `asset_relationships_provenance_class_check`, `relationship_not_self`, `relationship_validity`.
Exclusion constraints: `relationship_no_overlap`.
Keys: 1 primary key, 2 foreign key, 0 unique.

### `assets`

Facility assets. Currently fictional only and always SYNTHETIC. Geometry is added in Gate 4.

| Column | Type | Null | Description |
|---|---|---|---|
| `asset_id` | text | no |  |
| `facility_id` | text | no |  |
| `parent_asset_id` | text | yes |  |
| `asset_type` | text | no |  |
| `asset_name` | text | no |  |
| `equipment_class_id` | text | yes |  |
| `operating_status` | text | yes |  |
| `geometry` | geometry(Point,4326) | yes |  |
| `is_fictional` | boolean | no |  |
| `provenance_class` | provenance_class | no |  |
| `transformation_id` | text | no |  |
| `created_at` | timestamp with time zone | no |  |

Check constraints: `assets_is_fictional_check`, `assets_provenance_class_check`.
Keys: 1 primary key, 4 foreign key, 1 unique.

### `audit_events`

| Column | Type | Null | Description |
|---|---|---|---|
| `event_id` | bigint | no |  |
| `actor_id` | text | no |  |
| `operation` | text | no |  |
| `target_id` | text | no |  |
| `timestamp` | timestamp with time zone | no |  |
| `correlation_id` | text | no |  |
| `before_state_reference` | text | yes |  |
| `after_state_reference` | text | yes |  |

Keys: 1 primary key, 0 foreign key, 0 unique.

### `batch_files`

Raw files behind a batch, so a canonical row can be traced to bytes on disk.

| Column | Type | Null | Description |
|---|---|---|---|
| `batch_id` | text | no |  |
| `path` | text | no |  |
| `sha256` | text | no |  |
| `size_bytes` | bigint | no |  |
| `source_url` | text | no |  |
| `source_modified` | text | yes |  |
| `upstream_checksum` | text | yes |  |

Check constraints: `batch_files_sha256_check`, `batch_files_size_bytes_check`.
Keys: 1 primary key, 1 foreign key, 0 unique.

### `data_quality_exceptions`

Every known defect, with the original value, evidence, and decision. Exceptions never alter source values.

| Column | Type | Null | Description |
|---|---|---|---|
| `exception_id` | bigint | no |  |
| `exception_type` | text | no |  |
| `severity` | text | no |  |
| `source_system_id` | text | no |  |
| `batch_id` | text | no |  |
| `dataset` | text | no |  |
| `source_asset_id` | text | yes |  |
| `source_record_key` | text | no |  |
| `field_name` | text | yes |  |
| `original_values` | jsonb | no |  |
| `evidence` | jsonb | no |  |
| `rule_id` | text | no |  |
| `disposition` | text | no |  |
| `status` | text | no |  |
| `decision_rationale` | text | no |  |
| `detected_at` | timestamp with time zone | no |  |

Check constraints: `data_quality_exceptions_disposition_check`, `data_quality_exceptions_severity_check`, `data_quality_exceptions_status_check`.
Keys: 1 primary key, 3 foreign key, 1 unique.

### `detector_alarms`

Alarm starts from the Gate 5 detector on simulated telemetry. A score is never a failure probability.

| Column | Type | Null | Description |
|---|---|---|---|
| `alarm_id` | text | no |  |
| `scenario_id` | text | no |  |
| `scenario_run_id` | text | no |  |
| `started_at` | timestamp with time zone | no |  |
| `score` | double precision | no |  |
| `threshold` | double precision | no |  |
| `model_id` | text | no |  |
| `model_version` | text | no |  |
| `model_sha256` | text | no |  |
| `evidence` | jsonb | no |  |
| `earlier_starts_in_lookback` | integer | no |  |
| `first_alarm_at` | timestamp with time zone | no |  |
| `provenance_class` | provenance_class | no |  |
| `input_provenance` | provenance_class | no |  |

Check constraints: `alarm_crossed_threshold`, `detector_alarms_check`, `detector_alarms_earlier_starts_in_lookback_check`, `detector_alarms_evidence_check`, `detector_alarms_input_provenance_check`, `detector_alarms_model_sha256_check`, `detector_alarms_provenance_class_check`.
Keys: 1 primary key, 2 foreign key, 0 unique.

### `domain_boundaries`

Whether a source may be mapped onto a target domain. A missing row means refused.

| Column | Type | Null | Description |
|---|---|---|---|
| `source_system_id` | text | no |  |
| `target_domain` | text | no |  |
| `is_allowed` | boolean | no |  |
| `rationale` | text | no |  |

Check constraints: `domain_boundaries_target_domain_check`.
Keys: 1 primary key, 1 foreign key, 0 unique.

### `domain_compatibility_assessments`

Engineering judgment, versioned. Not field validation. Generated from data_contracts/semantic_mappings/3w_aether_compatibility.yaml.

| Column | Type | Null | Description |
|---|---|---|---|
| `assessment_id` | text | no |  |
| `source_system_id` | text | no |  |
| `subject_type` | text | no |  |
| `subject_id` | text | no |  |
| `target_equipment_class_id` | text | no |  |
| `classification` | compatibility_class | no |  |
| `reasoning` | text | no |  |
| `conditions` | jsonb | no |  |
| `assessment_version` | integer | no |  |
| `assessed_on` | date | no |  |

Check constraints: `conditional_states_conditions`, `domain_compatibility_assessments_subject_type_check`.
Keys: 1 primary key, 2 foreign key, 1 unique.

### `domain_compatibility_requirements`

Equipment and operating conditions that telemetry must meet before it can be applied to an experimental asset.

| Column | Type | Null | Description |
|---|---|---|---|
| `requirement_id` | text | no |  |
| `target_equipment_class_id` | text | no |  |
| `category` | text | no |  |
| `requirement` | text | no |  |
| `target_value` | text | no |  |
| `rationale` | text | no |  |

Keys: 1 primary key, 1 foreign key, 0 unique.

### `equipment_classes`

Physical classes of equipment. Measurement semantics belong to a class, which is what keeps offshore and onshore measurements apart.

| Column | Type | Null | Description |
|---|---|---|---|
| `equipment_class_id` | text | no |  |
| `name` | text | no |  |
| `domain` | text | no |  |
| `description` | text | no |  |
| `basis` | text | no |  |

Check constraints: `equipment_classes_domain_check`.
Keys: 1 primary key, 0 foreign key, 0 unique.

### `equipment_measurement_capabilities`

Which measurements a class can provide. SOURCE_REPORTED means the source publishes it; the others are AETHER design assumptions.

| Column | Type | Null | Description |
|---|---|---|---|
| `equipment_class_id` | text | no |  |
| `measurement_definition_id` | text | no |  |
| `capability` | text | no |  |
| `basis` | text | no |  |

Check constraints: `equipment_measurement_capabilities_capability_check`.
Keys: 1 primary key, 2 foreign key, 0 unique.

### `equipment_relationship_rules`

The fictional facility's allowed flow connections. Anything not listed is refused.

| Column | Type | Null | Description |
|---|---|---|---|
| `source_asset_type` | text | no |  |
| `relationship_type` | text | no |  |
| `target_asset_type` | text | no |  |
| `rationale` | text | no |  |

Keys: 1 primary key, 0 foreign key, 0 unique.

### `facilities`

| Column | Type | Null | Description |
|---|---|---|---|
| `facility_id` | text | no |  |
| `facility_name` | text | no |  |
| `facility_type` | text | no |  |
| `region` | text | no |  |
| `is_fictional` | boolean | no |  |
| `disclosure` | text | no |  |
| `geometry` | geometry(Geometry,4326) | yes |  |
| `created_at` | timestamp with time zone | no |  |

Check constraints: `aether_is_fictional`.
Keys: 1 primary key, 0 foreign key, 1 unique.

### `ingestion_batches`

One row per acquisition manifest. Accepted plus rejected must equal the source count.

| Column | Type | Null | Description |
|---|---|---|---|
| `batch_id` | text | no |  |
| `source_system_id` | text | no |  |
| `source_version` | text | no |  |
| `ingestion_timestamp` | timestamp with time zone | no |  |
| `original_checksum` | text | no |  |
| `source_record_count` | integer | no |  |
| `accepted_count` | integer | no |  |
| `rejected_count` | integer | no |  |
| `processing_status` | text | no |  |
| `manifest_uri` | text | no |  |
| `notes` | jsonb | no |  |

Check constraints: `batch_counts_reconcile`, `ingestion_batches_accepted_count_check`, `ingestion_batches_original_checksum_check`, `ingestion_batches_processing_status_check`, `ingestion_batches_rejected_count_check`, `ingestion_batches_source_record_count_check`.
Keys: 1 primary key, 1 foreign key, 1 unique.

### `inspection_observations`

| Column | Type | Null | Description |
|---|---|---|---|
| `inspection_id` | bigint | no |  |
| `observation_id` | bigint | no |  |
| `inspection_type` | text | no |  |
| `source_asset_candidate_id` | text | yes |  |
| `asset_candidate_id` | text | yes |  |
| `evidence_uri` | text | no |  |
| `finding` | text | yes |  |
| `reviewer` | text | yes |  |
| `confidence` | double precision | yes |  |
| `review_status` | text | no |  |

Check constraints: `candidate_is_real_or_fictional`, `inspection_observations_confidence_check`, `inspection_observations_review_status_check`, `reviewed_has_reviewer`.
Keys: 1 primary key, 3 foreign key, 0 unique.

### `inspection_requests`

Simulated inspection requests on fictional assets. No priority score; Gate 7 owns prioritization.

| Column | Type | Null | Description |
|---|---|---|---|
| `request_id` | text | no |  |
| `asset_id` | text | no |  |
| `affected_asset_id` | text | no |  |
| `scenario_id` | text | no |  |
| `scenario_run_id` | text | no |  |
| `trigger_event_id` | text | no |  |
| `inspection_type` | text | no |  |
| `reason` | text | no |  |
| `status` | text | no |  |
| `created_at` | timestamp with time zone | no |  |
| `provenance_class` | provenance_class | no |  |

Check constraints: `inspection_requests_inspection_type_check`, `inspection_requests_provenance_class_check`, `inspection_requests_status_check`.
Keys: 1 primary key, 5 foreign key, 0 unique.

### `inspection_review_events`

Reviewer findings on real aerial evidence. No outcome confirms a leak or names a source.

| Column | Type | Null | Description |
|---|---|---|---|
| `review_id` | text | no |  |
| `evidence_id` | text | no |  |
| `evidence_kind` | text | no |  |
| `observation_id` | bigint | no |  |
| `reviewer` | text | no |  |
| `outcome` | text | no |  |
| `visible_features` | text[] | no |  |
| `blinded_to_plume_status` | boolean | no |  |
| `supersedes` | text | yes |  |
| `recorded_at` | timestamp with time zone | no |  |
| `provenance_class` | provenance_class | no |  |

Check constraints: `inspection_review_events_blinded_to_plume_status_check`, `inspection_review_events_evidence_kind_check`, `inspection_review_events_outcome_check`, `inspection_review_events_provenance_class_check`, `inspection_review_events_reviewer_check`, `inspection_review_events_visible_features_check`.
Keys: 1 primary key, 2 foreign key, 0 unique.

### `measurement_definitions`

A measurement belongs to one equipment class. There is no shared generic pressure definition.

| Column | Type | Null | Description |
|---|---|---|---|
| `measurement_definition_id` | text | no |  |
| `equipment_class_id` | text | no |  |
| `physical_quantity` | text | no |  |
| `equipment_location` | text | no |  |
| `reference_type` | reference_type | no |  |
| `canonical_unit_id` | text | no |  |
| `description` | text | no |  |

Check constraints: `definition_reference_fits_quantity`.
Keys: 1 primary key, 2 foreign key, 1 unique.

### `observations`

Queryable metadata. High-volume sensor values stay in Parquet; one TELEMETRY_SERIES row describes each sensor in each instance.

| Column | Type | Null | Description |
|---|---|---|---|
| `observation_id` | bigint | no |  |
| `source_system_id` | text | no |  |
| `source_record_id` | text | no |  |
| `observed_at` | timestamp without time zone | yes | As reported, with no time zone assumed. |
| `observation_type` | text | no |  |
| `metric_name` | text | no |  |
| `numeric_value` | double precision | yes |  |
| `unit_id` | text | yes |  |
| `quality_flag` | text | no |  |
| `geometry` | geometry(Geometry,4326) | yes |  |
| `provenance_class` | provenance_class | no |  |
| `original_record_uri` | text | no |  |
| `sensor_tag_id` | text | yes |  |
| `telemetry_event_id` | text | yes |  |
| `value_count` | integer | yes |  |
| `null_count` | integer | yes |  |
| `replayed_from_observation_id` | bigint | yes |  |
| `scenario_id` | text | yes |  |
| `batch_id` | text | yes |  |
| `transformation_id` | text | no |  |
| `scenario_run_id` | text | yes |  |

Check constraints: `observations_null_count_check`, `observations_observation_type_check`, `observations_value_count_check`, `observed_has_batch`, `replay_keeps_origin`, `simulated_series_is_synthetic`, `synthetic_source_requires_run`, `synthetic_source_requires_sensor`.
Keys: 1 primary key, 10 foreign key, 1 unique.

### `physical_connection_rules`

Allowed physical connections. Anything not listed is refused.

| Column | Type | Null | Description |
|---|---|---|---|
| `edge_type` | text | no |  |
| `from_node_type` | text | no |  |
| `to_node_type` | text | no |  |

Keys: 1 primary key, 0 foreign key, 0 unique.

### `physical_edges`

Directed connections. A closed valve or stopped machine is a run state, so this graph stays fixed.

| Column | Type | Null | Description |
|---|---|---|---|
| `edge_id` | text | no |  |
| `edge_type` | text | no |  |
| `from_node_id` | text | no |  |
| `to_node_id` | text | no |  |
| `element_asset_id` | text | no |  |
| `valve_asset_id` | text | yes |  |
| `length_m` | double precision | yes |  |
| `diameter_m` | double precision | yes |  |
| `network_version` | integer | no |  |
| `provenance_class` | provenance_class | no |  |

Check constraints: `edge_not_self`, `physical_edges_diameter_m_check`, `physical_edges_edge_type_check`, `physical_edges_length_m_check`, `physical_edges_network_version_check`, `physical_edges_provenance_class_check`, `pipes_have_geometry`.
Keys: 1 primary key, 4 foreign key, 0 unique.

### `physical_nodes`

Places where pressure is defined, or fictional sites. Local metres from a fictional origin, so no real location is implied.

| Column | Type | Null | Description |
|---|---|---|---|
| `node_id` | text | no |  |
| `facility_id` | text | no |  |
| `node_type` | text | no |  |
| `asset_id` | text | no |  |
| `local_x_m` | double precision | yes |  |
| `local_y_m` | double precision | yes |  |
| `network_version` | integer | no |  |
| `provenance_class` | provenance_class | no |  |

Check constraints: `coordinates_together`, `physical_nodes_network_version_check`, `physical_nodes_node_type_check`, `physical_nodes_provenance_class_check`.
Keys: 1 primary key, 2 foreign key, 0 unique.

### `production_records`

One row per source row: completion, month, and product. Volumes are unaltered. v_production_wide gives the oil, gas, and water columns.

| Column | Type | Null | Description |
|---|---|---|---|
| `record_id` | bigint | no |  |
| `source_system_id` | text | no |  |
| `reporting_entity_id` | text | no |  |
| `reporting_grain` | text | no |  |
| `reporting_period` | date | no | First day of the month the fluid was produced. This is the production date. |
| `product_kind` | text | no |  |
| `reported_volume` | bigint | yes |  |
| `unit_id` | text | no |  |
| `unit_system` | text | no |  |
| `pool_code` | text | no |  |
| `operator_code` | text | no |  |
| `days_produced` | smallint | yes |  |
| `completion_status_code` | text | yes |  |
| `is_amended` | boolean | yes | OCD amend_ind. The current value replaced an earlier report, and the earlier value is not in the extract. |
| `source_effective_at` | timestamp without time zone | no | OCD eff_dte as reported, with no time zone stated. Not the production date. Filing-like in recent rows, but OCD does not define it as a filing date. |
| `source_modified_at` | timestamp without time zone | yes |  |
| `original_record_uri` | text | no |  |
| `provenance_class` | provenance_class | no |  |
| `batch_id` | text | no |  |
| `transformation_id` | text | no |  |
| `source_record_key` | text | no |  |

Check constraints: `production_records_days_produced_check`, `production_records_provenance_class_check`, `production_records_reported_volume_check`, `production_records_reporting_grain_check`, `production_records_reporting_period_check`.
Keys: 1 primary key, 5 foreign key, 1 unique.

### `production_unit_rules`

Verified meaning of each product kind. A production row must match a rule, so ambiguous units cannot be stored.

| Column | Type | Null | Description |
|---|---|---|---|
| `source_system_id` | text | no |  |
| `product_kind` | text | no |  |
| `unit_id` | text | no |  |
| `product_scope` | text | no |  |
| `base_conditions` | text | no |  |
| `verification_status` | verification_status | no |  |
| `evidence` | jsonb | no |  |

Check constraints: `unit_rule_has_evidence`.
Keys: 1 primary key, 2 foreign key, 1 unique.

### `recommendations`

Deterministic, explained recommendations. Every score point comes from a stored term.

| Column | Type | Null | Description |
|---|---|---|---|
| `recommendation_id` | text | no |  |
| `alarm_id` | text | no |  |
| `scenario_id` | text | no |  |
| `scenario_run_id` | text | no |  |
| `decided_at` | timestamp with time zone | no |  |
| `action` | text | no |  |
| `candidate_assets` | text[] | no |  |
| `suppressed_assets` | text[] | no |  |
| `priority_score` | integer | no |  |
| `priority_band` | text | yes |  |
| `respond_within_h` | integer | yes |  |
| `terms` | jsonb | no |  |
| `explanation` | jsonb | no |  |
| `rules_version` | integer | no |  |
| `provenance_class` | provenance_class | no |  |

Check constraints: `dispatch_has_band_and_candidate`, `recommendations_action_check`, `recommendations_explanation_check`, `recommendations_priority_band_check`, `recommendations_priority_score_check`, `recommendations_provenance_class_check`, `recommendations_respond_within_h_check`, `recommendations_rules_version_check`, `recommendations_terms_check`.
Keys: 1 primary key, 3 foreign key, 0 unique.

### `reconciliation_decisions`

Every reconciliation outcome with its identifiers, method, evidence, status, algorithm version, and time. Unknown stays UNRESOLVED.

| Column | Type | Null | Description |
|---|---|---|---|
| `decision_id` | bigint | no |  |
| `module` | text | no |  |
| `subject_type` | text | no |  |
| `subject_id` | text | no |  |
| `object_type` | text | yes |  |
| `object_id` | text | yes |  |
| `relationship_type` | text | no |  |
| `method` | text | no |  |
| `evidence` | jsonb | no |  |
| `confidence` | double precision | yes | Only where justified. Distance is not a probability, so proximity candidates leave this NULL. |
| `uncertainty` | jsonb | yes |  |
| `verification_status` | verification_status | no |  |
| `provenance_class` | provenance_class | no |  |
| `algorithm_version` | text | no |  |
| `decided_at` | timestamp with time zone | no |  |
| `batch_id` | text | yes |  |
| `supersedes_decision_id` | bigint | yes |  |
| `review_id` | bigint | yes |  |

Check constraints: `decision_has_evidence`, `experimental_is_never_verified`, `identity_never_involves_fictional`, `inferred_is_never_verified`, `object_type_and_id_together`, `proximity_is_only_a_candidate`, `real_never_relates_to_fictional`, `reconciliation_decisions_algorithm_version_check`, `reconciliation_decisions_confidence_check`, `reconciliation_decisions_module_check`, `reconciliation_decisions_object_type_check`, `reconciliation_decisions_relationship_type_check`, `reconciliation_decisions_subject_type_check`, `review_decisions_are_linked`, `reviewed_identity_cites_identifier`, `verified_identity_needs_identifier`, `verified_measurement_needs_declared_basis`, `weak_methods_cannot_assert_identity`.
Keys: 1 primary key, 3 foreign key, 0 unique.

### `reconciliation_reviews`

Human review of a decision. No automatic process writes here.

| Column | Type | Null | Description |
|---|---|---|---|
| `review_id` | bigint | no |  |
| `decision_id` | bigint | no |  |
| `reviewer` | text | no |  |
| `action` | text | no |  |
| `rationale` | text | no |  |
| `evidence` | jsonb | no |  |
| `reviewed_at` | timestamp with time zone | no |  |

Check constraints: `reconciliation_reviews_action_check`, `reconciliation_reviews_rationale_check`, `reconciliation_reviews_reviewer_check`.
Keys: 1 primary key, 1 foreign key, 0 unique.

### `scenario_mappings`

Explicit, immutable experimental association. Never OBSERVED, and a new version means a new row.

| Column | Type | Null | Description |
|---|---|---|---|
| `mapping_id` | bigint | no |  |
| `scenario_id` | text | no |  |
| `target_asset_id` | text | no |  |
| `telemetry_event_id` | text | no |  |
| `original_source_instance_id` | text | no |  |
| `transformation_config` | jsonb | no |  |
| `compatibility_assessment_id` | text | no |  |
| `conditions_satisfied` | jsonb | yes |  |
| `mapping_provenance` | provenance_class | no |  |
| `replay_start_time` | timestamp with time zone | yes |  |

Check constraints: `scenario_mappings_mapping_provenance_check`.
Keys: 1 primary key, 4 foreign key, 1 unique.

### `scenario_replays`

Replay cursor over stored simulator output. Replaying generates no data.

| Column | Type | Null | Description |
|---|---|---|---|
| `scenario_id` | text | no |  |
| `scenario_run_id` | text | no |  |
| `state` | text | no |  |
| `position_s` | integer | no |  |
| `speed` | double precision | no |  |
| `anchored_at` | timestamp with time zone | no |  |
| `updated_by` | text | no |  |

Check constraints: `replay_run_belongs_to_scenario`, `scenario_replays_position_s_check`, `scenario_replays_speed_check`, `scenario_replays_state_check`, `scenario_replays_updated_by_check`.
Keys: 1 primary key, 2 foreign key, 0 unique.

### `scenario_runs`

One simulator run on fictional assets, with its parameters, seed, and output checksum. Always SYNTHETIC, and immutable.

| Column | Type | Null | Description |
|---|---|---|---|
| `scenario_run_id` | text | no |  |
| `scenario_id` | text | no |  |
| `case_name` | text | no |  |
| `target_asset_id` | text | no |  |
| `affected_asset_id` | text | no |  |
| `simulator_name` | text | no |  |
| `simulator_version` | integer | no |  |
| `config_sha256` | text | no |  |
| `output_sha256` | text | no |  |
| `output_uri` | text | no |  |
| `random_seed` | bigint | no |  |
| `sample_count` | integer | no |  |
| `sampling_interval_s` | integer | no |  |
| `fault_onset_offset_s` | integer | yes |  |
| `parameters` | jsonb | no |  |
| `invariants` | jsonb | no |  |
| `provenance_class` | provenance_class | no |  |
| `transformation_id` | text | no |  |

Check constraints: `fault_case_has_known_onset`, `scenario_runs_case_name_check`, `scenario_runs_config_sha256_check`, `scenario_runs_output_sha256_check`, `scenario_runs_provenance_class_check`, `scenario_runs_sample_count_check`, `scenario_runs_sampling_interval_s_check`, `scenario_runs_simulator_version_check`.
Keys: 1 primary key, 4 foreign key, 2 unique.

### `scenarios`

| Column | Type | Null | Description |
|---|---|---|---|
| `scenario_id` | text | no |  |
| `scenario_name` | text | no |  |
| `scenario_description` | text | no |  |
| `target_facility_id` | text | no |  |
| `scenario_version` | integer | no |  |
| `random_seed` | bigint | no |  |
| `created_at` | timestamp with time zone | no |  |

Check constraints: `scenarios_scenario_version_check`.
Keys: 1 primary key, 1 foreign key, 0 unique.

### `sensor_tag_mappings`

Same-class semantic mappings. Crossing equipment domains is only possible through a compatibility assessment and an experimental scenario mapping.

| Column | Type | Null | Description |
|---|---|---|---|
| `mapping_id` | bigint | no |  |
| `tag_id` | text | no |  |
| `measurement_definition_id` | text | no |  |
| `equipment_class_id` | text | no |  |
| `reference_type` | reference_type | no |  |
| `source_system_id` | text | no |  |
| `original_unit_id` | text | no |  |
| `canonical_unit_id` | text | no |  |
| `conversion_method` | text | no |  |
| `data_quality_state` | text | no |  |
| `mapping_status` | verification_status | no |  |
| `rationale` | text | no |  |
| `valid_from` | date | no |  |
| `valid_to` | date | yes |  |

Check constraints: `sensor_tag_mappings_data_quality_state_check`, `tag_mapping_validity`.
Exclusion constraints: `tag_mapping_no_overlap`.
Keys: 1 primary key, 4 foreign key, 0 unique.

### `sensor_tags`

Native tags as published by the source, with their physical class and original unit.

| Column | Type | Null | Description |
|---|---|---|---|
| `tag_id` | text | no |  |
| `source_system_id` | text | no |  |
| `native_tag_name` | text | no |  |
| `canonical_metric` | text | yes |  |
| `equipment_position` | text | no |  |
| `equipment_class_id` | text | no |  |
| `physical_quantity` | text | no |  |
| `unit_id` | text | no |  |
| `pressure_reference_type` | reference_type | no |  |
| `sampling_frequency` | text | yes |  |
| `mapping_status` | verification_status | no |  |
| `source_description` | text | no |  |
| `fictional_asset_id` | text | yes | The fictional asset a synthetic sensor is installed on. Always NULL for source tags. |

Check constraints: `synthetic_sensor_has_fictional_asset`, `tag_reference_fits_quantity`.
Keys: 1 primary key, 4 foreign key, 2 unique.

### `shared_events`

One event contract for both domains, which stay separate. It carries no detection accuracy.

| Column | Type | Null | Description |
|---|---|---|---|
| `event_id` | text | no |  |
| `schema_version` | integer | no |  |
| `domain` | text | no |  |
| `event_kind` | text | no |  |
| `event_class` | text | no |  |
| `source_system_id` | text | no |  |
| `telemetry_event_id` | text | yes |  |
| `scenario_id` | text | yes |  |
| `scenario_run_id` | text | yes |  |
| `target_asset_id` | text | yes |  |
| `affected_asset_id` | text | yes |  |
| `onset_offset_s` | integer | yes |  |
| `evidence` | jsonb | no |  |
| `provenance_class` | provenance_class | no |  |
| `transformation_id` | text | no |  |

Check constraints: `aether_events_are_synthetic_and_scoped`, `benchmark_events_stay_independent`, `shared_events_domain_check`, `shared_events_event_kind_check`, `shared_events_evidence_check`, `shared_events_onset_offset_s_check`, `shared_events_schema_version_check`.
Keys: 1 primary key, 7 foreign key, 0 unique.

### `source_asset_history`

Temporal well records. OCD's 9999-12-31 sentinel is stored as an open-ended valid_to.

| Column | Type | Null | Description |
|---|---|---|---|
| `history_id` | bigint | no |  |
| `source_asset_id` | text | no |  |
| `valid_from` | date | no |  |
| `valid_to` | date | yes |  |
| `operator_code` | text | yes |  |
| `status_code` | text | yes |  |
| `well_type_code` | text | yes |  |
| `reported_latitude` | double precision | yes |  |
| `reported_longitude` | double precision | yes |  |
| `reported_datum_label` | text | yes |  |
| `attributes` | jsonb | no |  |
| `provenance_class` | provenance_class | no |  |
| `batch_id` | text | no |  |
| `transformation_id` | text | no |  |
| `source_record_key` | text | no |  |

Check constraints: `history_validity`, `source_asset_history_provenance_class_check`.
Exclusion constraints: `history_no_overlap`.
Keys: 1 primary key, 3 foreign key, 0 unique.

### `source_assets`

Real entities named by a source. Always OBSERVED, never part of AETHER Field.

| Column | Type | Null | Description |
|---|---|---|---|
| `source_asset_id` | text | no |  |
| `source_system_id` | text | no |  |
| `parent_source_asset_id` | text | yes |  |
| `asset_type` | text | no |  |
| `external_identifier` | text | no |  |
| `asset_name` | text | yes |  |
| `equipment_class_id` | text | no |  |
| `operating_status` | text | yes |  |
| `reported_latitude` | double precision | yes | As reported by the source. Never corrected, even when quarantined. |
| `reported_longitude` | double precision | yes |  |
| `reported_datum_label` | text | yes |  |
| `geometry` | geometry(Point,4269) | yes | NAD83 point, present only when spatial_status is USABLE. |
| `spatial_status` | spatial_status | no |  |
| `attributes` | jsonb | no |  |
| `provenance_class` | provenance_class | no |  |
| `batch_id` | text | no |  |
| `transformation_id` | text | no |  |
| `source_record_key` | text | no |  |
| `created_at` | timestamp with time zone | no |  |

Check constraints: `completion_has_parent`, `geometry_only_when_usable`, `source_assets_asset_type_check`, `source_assets_provenance_class_check`, `usable_geometry_is_valid`.
Keys: 1 primary key, 5 foreign key, 2 unique.

### `source_event_classes`

| Column | Type | Null | Description |
|---|---|---|---|
| `source_system_id` | text | no |  |
| `event_label` | smallint | no |  |
| `event_name` | text | no |  |
| `description` | text | no |  |
| `has_transient` | boolean | yes |  |

Keys: 1 primary key, 1 foreign key, 1 unique.

### `source_identifiers`

Source identifiers for real assets. canonical_asset_id references source_assets only, so no real identifier can resolve to a fictional asset.

| Column | Type | Null | Description |
|---|---|---|---|
| `identifier_id` | bigint | no |  |
| `source_system_id` | text | no |  |
| `canonical_asset_id` | text | yes |  |
| `external_identifier` | text | no |  |
| `identifier_type` | text | no |  |
| `valid_from` | date | no |  |
| `valid_to` | date | yes |  |
| `verification_status` | verification_status | no |  |

Check constraints: `identifier_validity`, `verified_identifier_has_asset`.
Exclusion constraints: `identifier_no_overlap`.
Keys: 1 primary key, 2 foreign key, 0 unique.

### `source_reconciliation_evidence`

Field-level comparisons between channels. channels_are_independent records whether agreement can count as confirmation. OCD ArcGIS and FTP are not independent.

| Column | Type | Null | Description |
|---|---|---|---|
| `evidence_id` | bigint | no |  |
| `source_asset_id` | text | no |  |
| `batch_id` | text | no |  |
| `field_name` | text | no |  |
| `channel_a` | text | no |  |
| `value_a` | text | yes |  |
| `channel_b` | text | no |  |
| `value_b` | text | yes |  |
| `outcome` | text | no |  |
| `channels_are_independent` | boolean | no |  |
| `method_version` | text | no |  |

Check constraints: `source_reconciliation_evidence_outcome_check`.
Keys: 1 primary key, 2 foreign key, 1 unique.

### `source_systems`

Each independent origin of data, including the project-generated synthetic source.

| Column | Type | Null | Description |
|---|---|---|---|
| `source_system_id` | text | no |  |
| `provider` | text | no |  |
| `source_url` | text | no |  |
| `source_version` | text | yes |  |
| `license` | text | no |  |
| `retrieval_timestamp` | timestamp with time zone | yes |  |
| `usage_constraints` | text | no |  |
| `is_project_generated` | boolean | no |  |

Keys: 1 primary key, 0 foreign key, 0 unique.

### `telemetry_events`

One row per 3W instance. Instance IDs repeat across classes, so identity includes the event label. Timestamps carry no stated time zone.

| Column | Type | Null | Description |
|---|---|---|---|
| `event_id` | text | no |  |
| `source_system_id` | text | no |  |
| `source_instance_id` | text | no |  |
| `source_asset_id` | text | yes |  |
| `source_event_label` | smallint | no |  |
| `source_event_class` | text | no |  |
| `start_timestamp` | timestamp without time zone | no |  |
| `end_timestamp` | timestamp without time zone | no |  |
| `real_or_simulated_source` | instance_origin | no |  |
| `observation_count` | integer | no |  |
| `parquet_uri` | text | no |  |
| `dataset_version` | text | no |  |
| `upstream_checksum` | text | no |  |
| `provenance_class` | provenance_class | no |  |
| `batch_id` | text | no |  |
| `transformation_id` | text | no |  |

Check constraints: `generated_instances_are_synthetic`, `only_real_instances_are_observed`, `real_instance_has_source_well`, `telemetry_events_observation_count_check`, `telemetry_time_order`.
Keys: 1 primary key, 5 foreign key, 2 unique.

### `transformations`

Provenance as a property of the process. Canonical rows reference this with a composite key, so a row cannot claim a class its transformation does not produce.

| Column | Type | Null | Description |
|---|---|---|---|
| `transformation_id` | text | no |  |
| `name` | text | no |  |
| `version` | integer | no |  |
| `code_reference` | text | no |  |
| `description` | text | no |  |
| `input_provenance` | provenance_class[] | no |  |
| `output_provenance` | provenance_class | no |  |
| `alters_values` | boolean | no |  |

Check constraints: `observed_output_is_unaltered`, `synthetic_input_cannot_become_derived`, `transformations_input_provenance_check`, `transformations_version_check`.
Keys: 1 primary key, 0 foreign key, 2 unique.

### `unit_conversions`

value_out = value_in * factor + term. Both units must measure the same quantity. Gauge-to-absolute changes are not unit conversions and are not representable here.

| Column | Type | Null | Description |
|---|---|---|---|
| `from_unit_id` | text | no |  |
| `to_unit_id` | text | no |  |
| `physical_quantity` | text | no |  |
| `factor` | double precision | no |  |
| `term` | double precision | no |  |
| `method` | text | no |  |

Keys: 1 primary key, 2 foreign key, 1 unique.

### `units`

| Column | Type | Null | Description |
|---|---|---|---|
| `unit_id` | text | no |  |
| `physical_quantity` | text | no |  |
| `description` | text | no |  |

Keys: 1 primary key, 0 foreign key, 1 unique.

### `work_order_transitions`

Authoritative work-order history. SCRIPTED_DEMO actors stand in for people in demonstration runs and are never human decisions.

| Column | Type | Null | Description |
|---|---|---|---|
| `transition_id` | bigint | no |  |
| `work_order_id` | bigint | no |  |
| `sequence` | integer | no |  |
| `decision` | text | no |  |
| `from_status` | text | yes |  |
| `to_status` | text | no |  |
| `actor_id` | text | no |  |
| `actor_kind` | text | no |  |
| `actor_role` | text | no |  |
| `justification` | text | no |  |
| `decided_at` | timestamp with time zone | no |  |
| `recorded_at` | timestamp with time zone | no |  |

Check constraints: `allowed_transition`, `only_the_engine_creates`, `supervisor_decides`, `work_order_transitions_actor_id_check`, `work_order_transitions_actor_kind_check`, `work_order_transitions_decision_check`, `work_order_transitions_justification_check`, `work_order_transitions_sequence_check`.
Keys: 1 primary key, 1 foreign key, 1 unique.

### `work_orders`

Simulated work on fictional assets. A work order requires a scenario and cannot point at a real well.

| Column | Type | Null | Description |
|---|---|---|---|
| `work_order_id` | bigint | no |  |
| `scenario_id` | text | no |  |
| `asset_id` | text | no |  |
| `recommended_action` | text | no |  |
| `severity` | text | no |  |
| `priority` | integer | no |  |
| `status` | text | no |  |
| `estimated_cost` | numeric(12,2) | yes |  |
| `evidence_reference` | text | no |  |
| `created_at` | timestamp with time zone | no |  |
| `external_id` | text | yes |  |
| `recommendation_id` | text | yes |  |
| `priority_band` | text | yes |  |

Check constraints: `work_orders_priority_band_check`, `work_orders_status_check`.
Keys: 1 primary key, 3 foreign key, 1 unique.

## Triggers

| Table | Trigger |
|---|---|
| `api_idempotency_keys` | `api_idempotency_keys_append_only` |
| `approval_events` | `approval_events_append_only` |
| `asset_observation_links` | `fictional_link_chain_guard` |
| `asset_observation_links` | `observation_link_guard` |
| `asset_relationships` | `asset_relationship_rule_guard` |
| `audit_events` | `audit_events_append_only` |
| `detector_alarms` | `detector_alarms_append_only` |
| `inspection_requests` | `inspection_request_trigger_guard` |
| `inspection_review_events` | `inspection_review_chain` |
| `inspection_review_events` | `inspection_review_events_append_only` |
| `observations` | `observation_sensor_source_guard` |
| `physical_edges` | `physical_edge_rule_guard` |
| `recommendations` | `recommendation_guard` |
| `recommendations` | `recommendations_append_only` |
| `reconciliation_decisions` | `reconciliation_decisions_append_only` |
| `reconciliation_reviews` | `reconciliation_reviews_append_only` |
| `scenario_mappings` | `scenario_mapping_guard` |
| `scenario_mappings` | `scenario_mapping_immutable` |
| `scenario_mappings` | `scenario_mapping_zz_boundary` |
| `scenario_runs` | `scenario_runs_immutable` |
| `shared_events` | `shared_event_origin_guard` |
| `shared_events` | `shared_events_immutable` |
| `work_order_transitions` | `work_order_transition_order` |
| `work_order_transitions` | `work_order_transitions_append_only` |
| `work_orders` | `work_order_creation_guard` |
| `work_orders` | `work_order_status_guard` |

## Views

- `v_current_reconciliation_decisions`: Decisions not yet superseded by a reviewed decision.
- `v_open_quality_exceptions`
- `v_production_lineage`
- `v_production_wide`: Oil, gas, and water per completion and month. A missing product stays NULL, never zero.
- `v_reconciliation_review_queue`: Open decisions awaiting human review. Nothing leaves this queue automatically.
- `v_spatially_usable_source_assets`: The only spatial population for analytics. Excludes quarantined coordinates and unresolved datums.
- `v_synthetic_provenance_chain`: Each synthetic observation with its asset, sensor, scenario, run, simulator version, and parameter set.
- `v_tag_semantics`: The nine required semantic attributes for each sensor measurement.
- `v_telemetry_lineage`
