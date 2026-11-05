-- Quality exceptions and reconciliation evidence.

CREATE TABLE data_quality_exceptions (
  exception_id       bigserial PRIMARY KEY,
  exception_type     text NOT NULL,
  severity           text NOT NULL CHECK (severity IN ('ERROR', 'WARNING', 'INFO')),
  source_system_id   text NOT NULL REFERENCES source_systems,
  batch_id           text NOT NULL REFERENCES ingestion_batches,
  dataset            text NOT NULL,
  source_asset_id    text REFERENCES source_assets,
  source_record_key  text NOT NULL,
  field_name         text,
  original_values    jsonb NOT NULL,
  evidence           jsonb NOT NULL,
  rule_id            text NOT NULL,
  disposition        text NOT NULL CHECK (disposition IN (
    'QUARANTINED_FROM_SPATIAL', 'QUARANTINED_RECORD', 'FLAGGED_UNRESOLVED', 'ACCEPTED_WITH_NOTE'
  )),
  status             text NOT NULL CHECK (status IN ('OPEN', 'ACCEPTED', 'RESOLVED')),
  decision_rationale text NOT NULL,
  detected_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (batch_id, rule_id, source_record_key)
);
COMMENT ON TABLE data_quality_exceptions IS 'Every known defect, with the original value, evidence, and decision. Exceptions never alter source values.';
CREATE INDEX quality_exceptions_asset_idx ON data_quality_exceptions (source_asset_id);

CREATE TABLE source_reconciliation_evidence (
  evidence_id       bigserial PRIMARY KEY,
  source_asset_id   text NOT NULL REFERENCES source_assets,
  batch_id          text NOT NULL REFERENCES ingestion_batches,
  field_name        text NOT NULL,
  channel_a         text NOT NULL,
  value_a           text,
  channel_b         text NOT NULL,
  value_b           text,
  outcome           text NOT NULL CHECK (outcome IN ('AGREE', 'CONFLICT', 'MISSING')),
  channels_are_independent boolean NOT NULL,
  method_version    text NOT NULL,
  UNIQUE (batch_id, source_asset_id, field_name, channel_a, channel_b)
);
COMMENT ON TABLE source_reconciliation_evidence IS 'Field-level comparisons between channels. channels_are_independent records whether agreement can count as confirmation. OCD ArcGIS and FTP are not independent.';
