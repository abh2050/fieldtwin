-- Operational entities from the specification. Tables and invariants only; workflows arrive in Gates 6 and 7.

CREATE TABLE inspection_observations (
  inspection_id      bigserial PRIMARY KEY,
  observation_id     bigint NOT NULL REFERENCES observations,
  inspection_type    text NOT NULL,
  source_asset_candidate_id text REFERENCES source_assets,
  asset_candidate_id text REFERENCES assets,
  evidence_uri       text NOT NULL,
  finding            text,
  reviewer           text,
  confidence         double precision CHECK (confidence BETWEEN 0 AND 1),
  review_status      text NOT NULL CHECK (review_status IN ('PENDING', 'REVIEWED', 'REJECTED')),
  CONSTRAINT candidate_is_real_or_fictional CHECK (num_nonnulls(source_asset_candidate_id, asset_candidate_id) <= 1),
  CONSTRAINT reviewed_has_reviewer CHECK (review_status = 'PENDING' OR reviewer IS NOT NULL)
);

CREATE TABLE anomaly_predictions (
  prediction_id      bigserial PRIMARY KEY,
  scenario_id        text REFERENCES scenarios,
  source_event_id    text NOT NULL REFERENCES telemetry_events,
  model_version      text NOT NULL,
  event_timestamp    timestamp NOT NULL,
  predicted_class    text NOT NULL,
  anomaly_score      double precision,
  decision_threshold double precision,
  evidence_reference text NOT NULL,
  provenance_class   provenance_class NOT NULL CHECK (provenance_class IN ('DERIVED', 'INFERRED', 'SYNTHETIC'))
);
CREATE INDEX anomaly_event_idx ON anomaly_predictions (source_event_id);

CREATE TABLE work_orders (
  work_order_id      bigserial PRIMARY KEY,
  scenario_id        text NOT NULL REFERENCES scenarios,
  asset_id           text NOT NULL REFERENCES assets,
  recommended_action text NOT NULL,
  severity           text NOT NULL,
  priority           integer NOT NULL,
  status             text NOT NULL CHECK (status IN ('RECOMMENDED', 'APPROVED', 'REJECTED', 'NEEDS_EVIDENCE', 'COMPLETED')),
  estimated_cost     numeric(12, 2),
  evidence_reference text NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE work_orders IS 'Simulated work on fictional assets. A work order requires a scenario and cannot point at a real well.';

CREATE TABLE approval_events (
  approval_id   bigserial PRIMARY KEY,
  work_order_id bigint NOT NULL REFERENCES work_orders,
  actor_id      text NOT NULL,
  action        text NOT NULL CHECK (action IN ('APPROVE', 'REJECT', 'REQUEST_EVIDENCE')),
  justification text NOT NULL,
  "timestamp"   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
  event_id       bigserial PRIMARY KEY,
  actor_id       text NOT NULL,
  operation      text NOT NULL,
  target_id      text NOT NULL,
  "timestamp"    timestamptz NOT NULL DEFAULT now(),
  correlation_id text NOT NULL,
  before_state_reference text,
  after_state_reference text
);
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION reject_change();
CREATE TRIGGER approval_events_append_only BEFORE UPDATE OR DELETE ON approval_events
  FOR EACH ROW EXECUTE FUNCTION reject_change();
