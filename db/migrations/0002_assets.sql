-- Real source assets and fictional facility assets are separate tables by design (ADR 0006).

CREATE TABLE source_assets (
  source_asset_id    text PRIMARY KEY,
  source_system_id   text NOT NULL REFERENCES source_systems,
  parent_source_asset_id text REFERENCES source_assets,
  asset_type         text NOT NULL CHECK (asset_type IN ('WELL', 'WELL_COMPLETION')),
  external_identifier text NOT NULL,
  asset_name         text,
  equipment_class_id text NOT NULL REFERENCES equipment_classes,
  operating_status   text,
  reported_latitude  double precision,
  reported_longitude double precision,
  reported_datum_label text,
  geometry           geometry(Point, 4269),
  spatial_status     spatial_status NOT NULL,
  attributes         jsonb NOT NULL DEFAULT '{}',
  provenance_class   provenance_class NOT NULL CHECK (provenance_class = 'OBSERVED'),
  batch_id           text NOT NULL,
  transformation_id  text NOT NULL,
  source_record_key  text NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_system_id, asset_type, external_identifier),
  UNIQUE (source_asset_id, source_system_id),
  FOREIGN KEY (batch_id, source_system_id) REFERENCES ingestion_batches (batch_id, source_system_id),
  FOREIGN KEY (transformation_id, provenance_class) REFERENCES transformations (transformation_id, output_provenance),
  -- Only coordinates accepted for analysis get a geometry. Reported values are always preserved.
  CONSTRAINT geometry_only_when_usable CHECK ((spatial_status = 'USABLE') = (geometry IS NOT NULL)),
  CONSTRAINT usable_geometry_is_valid CHECK (
    geometry IS NULL OR (ST_IsValid(geometry) AND ST_Y(geometry) BETWEEN -90 AND 90 AND ST_X(geometry) BETWEEN -180 AND 180)
  ),
  CONSTRAINT completion_has_parent CHECK ((asset_type = 'WELL_COMPLETION') = (parent_source_asset_id IS NOT NULL))
);
COMMENT ON TABLE source_assets IS 'Real entities named by a source. Always OBSERVED, never part of AETHER Field.';
COMMENT ON COLUMN source_assets.geometry IS 'NAD83 point, present only when spatial_status is USABLE.';
COMMENT ON COLUMN source_assets.reported_latitude IS 'As reported by the source. Never corrected, even when quarantined.';
CREATE INDEX source_assets_geometry_idx ON source_assets USING gist (geometry);
CREATE INDEX source_assets_parent_idx ON source_assets (parent_source_asset_id);

CREATE TABLE source_identifiers (
  identifier_id      bigserial PRIMARY KEY,
  source_system_id   text NOT NULL REFERENCES source_systems,
  canonical_asset_id text REFERENCES source_assets,
  external_identifier text NOT NULL,
  identifier_type    text NOT NULL,
  valid_from         date NOT NULL DEFAULT '-infinity',
  valid_to           date,
  verification_status verification_status NOT NULL,
  CONSTRAINT identifier_validity CHECK (valid_to IS NULL OR valid_to > valid_from),
  CONSTRAINT verified_identifier_has_asset CHECK (verification_status <> 'VERIFIED' OR canonical_asset_id IS NOT NULL),
  CONSTRAINT identifier_no_overlap EXCLUDE USING gist (
    source_system_id WITH =, identifier_type WITH =, external_identifier WITH =,
    daterange(valid_from, valid_to) WITH &&
  )
);
COMMENT ON TABLE source_identifiers IS 'Source identifiers for real assets. canonical_asset_id references source_assets only, so no real identifier can resolve to a fictional asset.';

CREATE TABLE source_asset_history (
  history_id         bigserial PRIMARY KEY,
  source_asset_id    text NOT NULL REFERENCES source_assets,
  valid_from         date NOT NULL,
  valid_to           date,
  operator_code      text,
  status_code        text,
  well_type_code     text,
  reported_latitude  double precision,
  reported_longitude double precision,
  reported_datum_label text,
  attributes         jsonb NOT NULL DEFAULT '{}',
  provenance_class   provenance_class NOT NULL CHECK (provenance_class = 'OBSERVED'),
  batch_id           text NOT NULL REFERENCES ingestion_batches,
  transformation_id  text NOT NULL,
  source_record_key  text NOT NULL,
  FOREIGN KEY (transformation_id, provenance_class) REFERENCES transformations (transformation_id, output_provenance),
  CONSTRAINT history_validity CHECK (valid_to IS NULL OR valid_to > valid_from),
  CONSTRAINT history_no_overlap EXCLUDE USING gist (source_asset_id WITH =, daterange(valid_from, valid_to) WITH &&)
);
COMMENT ON TABLE source_asset_history IS 'Temporal well records. OCD''s 9999-12-31 sentinel is stored as an open-ended valid_to.';

CREATE TABLE facilities (
  facility_id   text PRIMARY KEY,
  facility_name text NOT NULL,
  facility_type text NOT NULL,
  region        text NOT NULL,
  is_fictional  boolean NOT NULL,
  disclosure    text NOT NULL,
  geometry      geometry(Geometry, 4326),
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (facility_id, is_fictional),
  CONSTRAINT aether_is_fictional CHECK (facility_id <> 'AETHER-FIELD' OR is_fictional)
);
CREATE INDEX facilities_geometry_idx ON facilities USING gist (geometry);

CREATE TABLE assets (
  asset_id          text PRIMARY KEY,
  facility_id       text NOT NULL,
  parent_asset_id   text REFERENCES assets,
  asset_type        text NOT NULL,
  asset_name        text NOT NULL,
  equipment_class_id text REFERENCES equipment_classes,
  operating_status  text,
  geometry          geometry(Point, 4326),
  is_fictional      boolean NOT NULL CHECK (is_fictional),
  provenance_class  provenance_class NOT NULL CHECK (provenance_class = 'SYNTHETIC'),
  transformation_id text NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (asset_id, equipment_class_id),
  FOREIGN KEY (facility_id, is_fictional) REFERENCES facilities (facility_id, is_fictional),
  FOREIGN KEY (transformation_id, provenance_class) REFERENCES transformations (transformation_id, output_provenance)
);
COMMENT ON TABLE assets IS 'Facility assets. Currently fictional only and always SYNTHETIC. Geometry is added in Gate 4.';
CREATE INDEX assets_geometry_idx ON assets USING gist (geometry);
CREATE INDEX assets_parent_idx ON assets (parent_asset_id);

CREATE TABLE asset_relationships (
  relationship_id   bigserial PRIMARY KEY,
  source_asset_id   text NOT NULL REFERENCES assets,
  target_asset_id   text NOT NULL REFERENCES assets,
  relationship_type text NOT NULL,
  evidence_type     text NOT NULL,
  provenance_class  provenance_class NOT NULL CHECK (provenance_class IN ('SYNTHETIC', 'INFERRED')),
  effective_from    date NOT NULL DEFAULT '-infinity',
  effective_to      date,
  CONSTRAINT relationship_not_self CHECK (source_asset_id <> target_asset_id),
  CONSTRAINT relationship_validity CHECK (effective_to IS NULL OR effective_to > effective_from),
  CONSTRAINT relationship_no_overlap EXCLUDE USING gist (
    source_asset_id WITH =, target_asset_id WITH =, relationship_type WITH =,
    daterange(effective_from, effective_to) WITH &&
  )
);
COMMENT ON TABLE asset_relationships IS 'Relationships between fictional assets. They can never be OBSERVED.';
