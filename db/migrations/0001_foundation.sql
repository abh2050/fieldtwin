-- Extensions, enumerations, source systems, batches, transformations, and units.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TYPE provenance_class AS ENUM ('OBSERVED', 'DERIVED', 'REPLAYED', 'SYNTHETIC', 'INFERRED');
CREATE TYPE verification_status AS ENUM ('VERIFIED', 'UNVERIFIED', 'UNRESOLVED', 'REJECTED');
CREATE TYPE reference_type AS ENUM ('ABSOLUTE', 'GAUGE', 'DIFFERENTIAL', 'UNKNOWN', 'NOT_APPLICABLE');
CREATE TYPE compatibility_class AS ENUM (
  'DIRECTLY_COMPATIBLE', 'CONDITIONALLY_COMPATIBLE', 'INCOMPATIBLE', 'INSUFFICIENT_EVIDENCE'
);
CREATE TYPE spatial_status AS ENUM ('USABLE', 'QUARANTINED', 'UNRESOLVED_DATUM', 'NO_LOCATION');
CREATE TYPE instance_origin AS ENUM ('REAL', 'SIMULATED', 'HAND_DRAWN');

CREATE TABLE source_systems (
  source_system_id   text PRIMARY KEY,
  provider           text NOT NULL,
  source_url         text NOT NULL,
  source_version     text,
  license            text NOT NULL,
  retrieval_timestamp timestamptz,
  usage_constraints  text NOT NULL,
  is_project_generated boolean NOT NULL DEFAULT false
);
COMMENT ON TABLE source_systems IS 'Each independent origin of data, including the project-generated synthetic source.';

CREATE TABLE ingestion_batches (
  batch_id            text PRIMARY KEY,
  source_system_id    text NOT NULL REFERENCES source_systems,
  source_version      text NOT NULL,
  ingestion_timestamp timestamptz NOT NULL,
  original_checksum   text NOT NULL CHECK (original_checksum ~ '^[0-9a-f]{64}$'),
  source_record_count integer NOT NULL CHECK (source_record_count >= 0),
  accepted_count      integer NOT NULL CHECK (accepted_count >= 0),
  rejected_count      integer NOT NULL CHECK (rejected_count >= 0),
  processing_status   text NOT NULL CHECK (processing_status IN ('COMPLETE', 'FAILED')),
  manifest_uri        text NOT NULL,
  notes               jsonb NOT NULL DEFAULT '[]',
  UNIQUE (batch_id, source_system_id),
  CONSTRAINT batch_counts_reconcile CHECK (accepted_count + rejected_count = source_record_count)
);
COMMENT ON TABLE ingestion_batches IS 'One row per acquisition manifest. Accepted plus rejected must equal the source count.';

CREATE TABLE batch_files (
  batch_id          text NOT NULL REFERENCES ingestion_batches,
  path              text NOT NULL,
  sha256            text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes        bigint NOT NULL CHECK (size_bytes >= 0),
  source_url        text NOT NULL,
  source_modified   text,
  upstream_checksum text,
  PRIMARY KEY (batch_id, path)
);
COMMENT ON TABLE batch_files IS 'Raw files behind a batch, so a canonical row can be traced to bytes on disk.';

CREATE TABLE transformations (
  transformation_id text NOT NULL PRIMARY KEY,
  name              text NOT NULL,
  version           integer NOT NULL CHECK (version > 0),
  code_reference    text NOT NULL,
  description       text NOT NULL,
  input_provenance  provenance_class[] NOT NULL CHECK (cardinality(input_provenance) > 0),
  output_provenance provenance_class NOT NULL,
  alters_values     boolean NOT NULL,
  UNIQUE (name, version),
  UNIQUE (transformation_id, output_provenance),
  -- A record can stay OBSERVED only if it came from observed input with its values unchanged.
  CONSTRAINT observed_output_is_unaltered CHECK (
    output_provenance <> 'OBSERVED'
    OR (input_provenance = ARRAY['OBSERVED']::provenance_class[] AND NOT alters_values)
  ),
  -- Anything computed from synthetic input stays synthetic.
  CONSTRAINT synthetic_input_cannot_become_derived CHECK (
    output_provenance NOT IN ('DERIVED', 'OBSERVED') OR NOT ('SYNTHETIC' = ANY (input_provenance))
  )
);
COMMENT ON TABLE transformations IS 'Provenance as a property of the process. Canonical rows reference this with a composite key, so a row cannot claim a class its transformation does not produce.';

CREATE TABLE units (
  unit_id          text PRIMARY KEY,
  physical_quantity text NOT NULL,
  description      text NOT NULL,
  UNIQUE (unit_id, physical_quantity)
);

CREATE TABLE unit_conversions (
  from_unit_id      text NOT NULL,
  to_unit_id        text NOT NULL,
  physical_quantity text NOT NULL,
  factor            double precision NOT NULL,
  term              double precision NOT NULL DEFAULT 0,
  method            text NOT NULL,
  PRIMARY KEY (from_unit_id, to_unit_id),
  UNIQUE (from_unit_id, to_unit_id, method),
  FOREIGN KEY (from_unit_id, physical_quantity) REFERENCES units (unit_id, physical_quantity),
  FOREIGN KEY (to_unit_id, physical_quantity) REFERENCES units (unit_id, physical_quantity)
);
COMMENT ON TABLE unit_conversions IS 'value_out = value_in * factor + term. Both units must measure the same quantity. Gauge-to-absolute changes are not unit conversions and are not representable here.';

CREATE TABLE equipment_classes (
  equipment_class_id text PRIMARY KEY,
  name               text NOT NULL,
  domain             text NOT NULL CHECK (domain IN ('REAL_ONSHORE', 'REAL_OFFSHORE', 'FICTIONAL_ONSHORE')),
  description        text NOT NULL,
  basis              text NOT NULL
);
COMMENT ON TABLE equipment_classes IS 'Physical classes of equipment. Measurement semantics belong to a class, which is what keeps offshore and onshore measurements apart.';
