-- Read views for analytics and source-to-canonical lineage.

CREATE VIEW v_spatially_usable_source_assets AS
SELECT source_asset_id, source_system_id, asset_type, external_identifier, operating_status, geometry
FROM source_assets
WHERE spatial_status = 'USABLE' AND geometry IS NOT NULL;
COMMENT ON VIEW v_spatially_usable_source_assets IS 'The only spatial population for analytics. Excludes quarantined coordinates and unresolved datums.';

CREATE VIEW v_production_wide AS
SELECT
  source_system_id,
  reporting_entity_id,
  reporting_grain,
  reporting_period,
  max(reported_volume) FILTER (WHERE product_kind = 'O') AS oil_volume_bbl,
  max(reported_volume) FILTER (WHERE product_kind = 'G') AS gas_volume_mcf_15025psia_60f,
  max(reported_volume) FILTER (WHERE product_kind = 'W') AS water_volume_bbl
FROM production_records
GROUP BY source_system_id, reporting_entity_id, reporting_grain, reporting_period;
COMMENT ON VIEW v_production_wide IS 'Oil, gas, and water per completion and month. A missing product stays NULL, never zero.';

CREATE VIEW v_production_lineage AS
SELECT
  p.record_id,
  p.reporting_entity_id,
  parent.external_identifier AS api_number,
  p.reporting_period,
  p.product_kind,
  p.reported_volume,
  p.unit_id,
  p.source_effective_at,
  p.provenance_class,
  p.source_record_key,
  p.original_record_uri,
  t.transformation_id,
  t.code_reference,
  t.alters_values,
  b.batch_id,
  b.source_system_id,
  b.source_version,
  b.manifest_uri,
  f.path AS raw_file_path,
  f.sha256 AS raw_file_sha256,
  f.source_url AS raw_file_source_url
FROM production_records p
JOIN source_assets c ON c.source_asset_id = p.reporting_entity_id
JOIN source_assets parent ON parent.source_asset_id = c.parent_source_asset_id
JOIN transformations t ON t.transformation_id = p.transformation_id
JOIN ingestion_batches b ON b.batch_id = p.batch_id
JOIN batch_files f ON f.batch_id = p.batch_id AND f.path = p.original_record_uri;

CREATE VIEW v_telemetry_lineage AS
SELECT
  e.event_id,
  e.source_instance_id,
  e.source_event_label,
  e.source_event_class,
  e.real_or_simulated_source,
  e.provenance_class,
  e.source_asset_id,
  e.dataset_version,
  e.parquet_uri,
  t.transformation_id,
  t.code_reference,
  b.batch_id,
  b.manifest_uri,
  f.sha256 AS raw_file_sha256,
  f.upstream_checksum,
  f.source_url AS raw_file_source_url
FROM telemetry_events e
JOIN transformations t ON t.transformation_id = e.transformation_id
JOIN ingestion_batches b ON b.batch_id = e.batch_id
JOIN batch_files f ON f.batch_id = e.batch_id AND f.path = e.parquet_uri;

CREATE VIEW v_open_quality_exceptions AS
SELECT exception_id, exception_type, severity, dataset, source_asset_id, source_record_key, disposition, status, decision_rationale
FROM data_quality_exceptions
WHERE status = 'OPEN';

CREATE VIEW v_tag_semantics AS
SELECT
  s.tag_id,
  s.native_tag_name AS original_source_tag,
  s.physical_quantity,
  s.equipment_position AS equipment_location,
  s.pressure_reference_type AS measurement_reference_type,
  s.unit_id AS original_unit,
  m.canonical_unit_id AS canonical_unit,
  m.conversion_method,
  s.source_system_id AS source_system,
  m.data_quality_state,
  m.measurement_definition_id,
  s.equipment_class_id
FROM sensor_tags s
LEFT JOIN sensor_tag_mappings m ON m.tag_id = s.tag_id;
COMMENT ON VIEW v_tag_semantics IS 'The nine required semantic attributes for each sensor measurement.';
