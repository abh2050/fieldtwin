-- What each sensor measures, where, and in what reference frame (ADR 0009).

CREATE TABLE measurement_definitions (
  measurement_definition_id text PRIMARY KEY,
  equipment_class_id text NOT NULL REFERENCES equipment_classes,
  physical_quantity  text NOT NULL,
  equipment_location text NOT NULL,
  reference_type     reference_type NOT NULL,
  canonical_unit_id  text NOT NULL,
  description        text NOT NULL,
  FOREIGN KEY (canonical_unit_id, physical_quantity) REFERENCES units (unit_id, physical_quantity),
  UNIQUE (measurement_definition_id, equipment_class_id, reference_type, canonical_unit_id),
  CONSTRAINT definition_reference_fits_quantity CHECK (
    (physical_quantity = 'pressure' AND reference_type <> 'NOT_APPLICABLE')
    OR (physical_quantity <> 'pressure' AND reference_type = 'NOT_APPLICABLE')
  )
);
COMMENT ON TABLE measurement_definitions IS 'A measurement belongs to one equipment class. There is no shared generic pressure definition.';

CREATE TABLE equipment_measurement_capabilities (
  equipment_class_id text NOT NULL REFERENCES equipment_classes,
  measurement_definition_id text NOT NULL REFERENCES measurement_definitions,
  capability text NOT NULL CHECK (capability IN ('EXPECTED', 'OPTIONAL', 'SOURCE_REPORTED')),
  basis text NOT NULL,
  PRIMARY KEY (equipment_class_id, measurement_definition_id)
);
COMMENT ON TABLE equipment_measurement_capabilities IS 'Which measurements a class can provide. SOURCE_REPORTED means the source publishes it; the others are AETHER design assumptions.';

CREATE TABLE sensor_tags (
  tag_id             text PRIMARY KEY,
  source_system_id   text NOT NULL REFERENCES source_systems,
  native_tag_name    text NOT NULL,
  canonical_metric   text,
  equipment_position text NOT NULL,
  equipment_class_id text NOT NULL REFERENCES equipment_classes,
  physical_quantity  text NOT NULL,
  unit_id            text NOT NULL,
  pressure_reference_type reference_type NOT NULL,
  sampling_frequency text,
  mapping_status     verification_status NOT NULL,
  source_description text NOT NULL,
  UNIQUE (source_system_id, native_tag_name),
  UNIQUE (tag_id, equipment_class_id, pressure_reference_type, unit_id),
  FOREIGN KEY (unit_id, physical_quantity) REFERENCES units (unit_id, physical_quantity),
  CONSTRAINT tag_reference_fits_quantity CHECK (
    (physical_quantity = 'pressure' AND pressure_reference_type <> 'NOT_APPLICABLE')
    OR (physical_quantity <> 'pressure' AND pressure_reference_type = 'NOT_APPLICABLE')
  )
);
COMMENT ON TABLE sensor_tags IS 'Native tags as published by the source, with their physical class and original unit.';

CREATE TABLE sensor_tag_mappings (
  mapping_id         bigserial PRIMARY KEY,
  tag_id             text NOT NULL,
  measurement_definition_id text NOT NULL,
  equipment_class_id text NOT NULL,
  reference_type     reference_type NOT NULL,
  source_system_id   text NOT NULL REFERENCES source_systems,
  original_unit_id   text NOT NULL,
  canonical_unit_id  text NOT NULL,
  conversion_method  text NOT NULL,
  data_quality_state text NOT NULL CHECK (data_quality_state IN ('SEMANTICS_COMPLETE', 'SEMANTICS_INCOMPLETE', 'NOT_ASSESSED')),
  mapping_status     verification_status NOT NULL,
  rationale          text NOT NULL,
  valid_from         date NOT NULL DEFAULT '-infinity',
  valid_to           date,
  CONSTRAINT tag_mapping_validity CHECK (valid_to IS NULL OR valid_to > valid_from),
  CONSTRAINT tag_mapping_no_overlap EXCLUDE USING gist (
    tag_id WITH =, measurement_definition_id WITH =, daterange(valid_from, valid_to) WITH &&
  ),
  -- These two keys make the core rule declarative. Tag and definition must share an equipment class
  -- and a reference type, so offshore-to-onshore and UNKNOWN-to-GAUGE mappings cannot be stored.
  CONSTRAINT mapping_matches_tag FOREIGN KEY (tag_id, equipment_class_id, reference_type, original_unit_id)
    REFERENCES sensor_tags (tag_id, equipment_class_id, pressure_reference_type, unit_id),
  CONSTRAINT mapping_matches_definition FOREIGN KEY (measurement_definition_id, equipment_class_id, reference_type, canonical_unit_id)
    REFERENCES measurement_definitions (measurement_definition_id, equipment_class_id, reference_type, canonical_unit_id),
  CONSTRAINT mapping_has_conversion FOREIGN KEY (original_unit_id, canonical_unit_id, conversion_method)
    REFERENCES unit_conversions (from_unit_id, to_unit_id, method)
);
COMMENT ON TABLE sensor_tag_mappings IS 'Same-class semantic mappings. Crossing equipment domains is only possible through a compatibility assessment and an experimental scenario mapping.';
