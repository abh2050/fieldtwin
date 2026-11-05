-- Source records: production, telemetry instances, and observations.

CREATE TABLE production_unit_rules (
  source_system_id  text NOT NULL REFERENCES source_systems,
  product_kind      text NOT NULL,
  unit_id           text NOT NULL REFERENCES units,
  product_scope     text NOT NULL,
  base_conditions   text NOT NULL,
  verification_status verification_status NOT NULL,
  evidence          jsonb NOT NULL,
  PRIMARY KEY (source_system_id, product_kind),
  UNIQUE (source_system_id, product_kind, unit_id),
  CONSTRAINT unit_rule_has_evidence CHECK (jsonb_array_length(evidence) > 0)
);
COMMENT ON TABLE production_unit_rules IS 'Verified meaning of each product kind. A production row must match a rule, so ambiguous units cannot be stored.';

CREATE TABLE production_records (
  record_id          bigserial PRIMARY KEY,
  source_system_id   text NOT NULL REFERENCES source_systems,
  reporting_entity_id text NOT NULL,
  reporting_grain    text NOT NULL CHECK (reporting_grain IN ('WELL_COMPLETION', 'WELL', 'LEASE', 'OPERATOR')),
  reporting_period   date NOT NULL CHECK (EXTRACT(DAY FROM reporting_period) = 1),
  product_kind       text NOT NULL,
  reported_volume    bigint CHECK (reported_volume >= 0),
  unit_id            text NOT NULL,
  unit_system        text NOT NULL,
  pool_code          text NOT NULL,
  operator_code      text NOT NULL,
  days_produced      smallint CHECK (days_produced BETWEEN 0 AND 31),
  completion_status_code text,
  is_amended         boolean,
  source_effective_at timestamp NOT NULL,
  source_modified_at timestamp,
  original_record_uri text NOT NULL,
  provenance_class   provenance_class NOT NULL CHECK (provenance_class = 'OBSERVED'),
  batch_id           text NOT NULL,
  transformation_id  text NOT NULL,
  source_record_key  text NOT NULL,
  UNIQUE (reporting_entity_id, reporting_period, product_kind),
  FOREIGN KEY (reporting_entity_id, source_system_id) REFERENCES source_assets (source_asset_id, source_system_id),
  FOREIGN KEY (source_system_id, product_kind, unit_id) REFERENCES production_unit_rules (source_system_id, product_kind, unit_id),
  FOREIGN KEY (batch_id, source_system_id) REFERENCES ingestion_batches (batch_id, source_system_id),
  FOREIGN KEY (transformation_id, provenance_class) REFERENCES transformations (transformation_id, output_provenance)
);
COMMENT ON TABLE production_records IS 'One row per source row: completion, month, and product. Volumes are unaltered. v_production_wide gives the oil, gas, and water columns.';
COMMENT ON COLUMN production_records.reporting_period IS 'First day of the month the fluid was produced. This is the production date.';
COMMENT ON COLUMN production_records.source_effective_at IS 'OCD eff_dte as reported, with no time zone stated. Not the production date. Filing-like in recent rows, but OCD does not define it as a filing date.';
COMMENT ON COLUMN production_records.is_amended IS 'OCD amend_ind. The current value replaced an earlier report, and the earlier value is not in the extract.';
CREATE INDEX production_period_idx ON production_records (reporting_period);
CREATE INDEX production_batch_idx ON production_records (batch_id);

CREATE TABLE source_event_classes (
  source_system_id text NOT NULL REFERENCES source_systems,
  event_label      smallint NOT NULL,
  event_name       text NOT NULL,
  description      text NOT NULL,
  has_transient    boolean,
  PRIMARY KEY (source_system_id, event_label),
  UNIQUE (source_system_id, event_name)
);

CREATE TABLE telemetry_events (
  event_id           text PRIMARY KEY,
  source_system_id   text NOT NULL REFERENCES source_systems,
  source_instance_id text NOT NULL,
  source_asset_id    text,
  source_event_label smallint NOT NULL,
  source_event_class text NOT NULL,
  start_timestamp    timestamp NOT NULL,
  end_timestamp      timestamp NOT NULL,
  real_or_simulated_source instance_origin NOT NULL,
  observation_count  integer NOT NULL CHECK (observation_count >= 0),
  parquet_uri        text NOT NULL,
  dataset_version    text NOT NULL,
  upstream_checksum  text NOT NULL,
  provenance_class   provenance_class NOT NULL,
  batch_id           text NOT NULL,
  transformation_id  text NOT NULL,
  UNIQUE (source_system_id, source_event_label, source_instance_id),
  UNIQUE (event_id, source_instance_id),
  FOREIGN KEY (source_system_id, source_event_label) REFERENCES source_event_classes (source_system_id, event_label),
  FOREIGN KEY (source_asset_id, source_system_id) REFERENCES source_assets (source_asset_id, source_system_id),
  FOREIGN KEY (batch_id, source_system_id) REFERENCES ingestion_batches (batch_id, source_system_id),
  FOREIGN KEY (transformation_id, provenance_class) REFERENCES transformations (transformation_id, output_provenance),
  CONSTRAINT telemetry_time_order CHECK (end_timestamp >= start_timestamp),
  -- Generated series never get a well, and real ones must have one.
  CONSTRAINT real_instance_has_source_well CHECK ((real_or_simulated_source = 'REAL') = (source_asset_id IS NOT NULL)),
  CONSTRAINT only_real_instances_are_observed CHECK ((real_or_simulated_source = 'REAL') = (provenance_class = 'OBSERVED')),
  CONSTRAINT generated_instances_are_synthetic CHECK (real_or_simulated_source = 'REAL' OR provenance_class = 'SYNTHETIC')
);
COMMENT ON TABLE telemetry_events IS 'One row per 3W instance. Instance IDs repeat across classes, so identity includes the event label. Timestamps carry no stated time zone.';
CREATE INDEX telemetry_class_origin_idx ON telemetry_events (source_event_label, real_or_simulated_source);

CREATE TABLE observations (
  observation_id    bigserial PRIMARY KEY,
  source_system_id  text NOT NULL REFERENCES source_systems,
  source_record_id  text NOT NULL,
  observed_at       timestamp,
  observation_type  text NOT NULL CHECK (observation_type IN ('TELEMETRY_SERIES', 'POINT_VALUE', 'REMOTE_SENSING', 'IMAGE')),
  metric_name       text NOT NULL,
  numeric_value     double precision,
  unit_id           text REFERENCES units,
  quality_flag      text NOT NULL,
  geometry          geometry(Geometry, 4326),
  provenance_class  provenance_class NOT NULL,
  original_record_uri text NOT NULL,
  sensor_tag_id     text REFERENCES sensor_tags,
  telemetry_event_id text REFERENCES telemetry_events,
  value_count       integer CHECK (value_count >= 0),
  null_count        integer CHECK (null_count >= 0),
  replayed_from_observation_id bigint REFERENCES observations,
  scenario_id       text,
  batch_id          text REFERENCES ingestion_batches,
  transformation_id text NOT NULL,
  UNIQUE (source_system_id, source_record_id),
  FOREIGN KEY (transformation_id, provenance_class) REFERENCES transformations (transformation_id, output_provenance),
  -- A replayed row must point at its original and carry a scenario, so it can't pass as a live measurement.
  CONSTRAINT replay_keeps_origin CHECK (
    (provenance_class = 'REPLAYED') = (replayed_from_observation_id IS NOT NULL)
    AND (provenance_class <> 'REPLAYED' OR scenario_id IS NOT NULL)
  ),
  CONSTRAINT observed_has_batch CHECK (provenance_class <> 'OBSERVED' OR batch_id IS NOT NULL)
);
COMMENT ON TABLE observations IS 'Queryable metadata. High-volume sensor values stay in Parquet; one TELEMETRY_SERIES row describes each sensor in each instance.';
COMMENT ON COLUMN observations.observed_at IS 'As reported, with no time zone assumed.';
CREATE INDEX observations_event_idx ON observations (telemetry_event_id);
CREATE INDEX observations_tag_idx ON observations (sensor_tag_id);
CREATE INDEX observations_geometry_idx ON observations USING gist (geometry);
