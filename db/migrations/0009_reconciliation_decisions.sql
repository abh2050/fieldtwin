-- Reconciliation decisions and human review (ADR 0013). Append-only: a change is a new row.

CREATE TABLE reconciliation_decisions (
  decision_id         bigserial PRIMARY KEY,
  module              text NOT NULL CHECK (module IN ('IDENTITY', 'SEMANTIC', 'GEOSPATIAL', 'SCENARIO')),
  subject_type        text NOT NULL CHECK (subject_type IN (
    'SOURCE_ASSET', 'ASSET', 'SOURCE_RECORD', 'SOURCE_SYSTEM', 'SENSOR_TAG', 'OBSERVATION', 'SCENARIO_RUN'
  )),
  subject_id          text NOT NULL,
  object_type         text CHECK (object_type IN (
    'SOURCE_ASSET', 'ASSET', 'SOURCE_RECORD', 'SOURCE_SYSTEM', 'MEASUREMENT_DEFINITION'
  )),
  object_id           text,
  relationship_type   text NOT NULL CHECK (relationship_type IN (
    'SAME_AS', 'COMPLETION_OF', 'NO_CROSSWALK', 'SAME_MEASUREMENT',
    'PROXIMITY_CANDIDATE', 'EMISSION_NEAR', 'EXPERIMENTAL_ASSIGNMENT'
  )),
  method              text NOT NULL,
  evidence            jsonb NOT NULL,
  confidence          double precision CHECK (confidence BETWEEN 0 AND 1),
  uncertainty         jsonb,
  verification_status verification_status NOT NULL,
  provenance_class    provenance_class NOT NULL,
  algorithm_version   text NOT NULL CHECK (algorithm_version ~ '@[0-9]+$'),
  decided_at          timestamptz NOT NULL DEFAULT now(),
  batch_id            text REFERENCES ingestion_batches,
  supersedes_decision_id bigint REFERENCES reconciliation_decisions,
  review_id           bigint,
  CONSTRAINT decision_has_evidence CHECK (jsonb_typeof(evidence) = 'object' AND evidence <> '{}'::jsonb),
  CONSTRAINT object_type_and_id_together CHECK ((object_type IS NULL) = (object_id IS NULL)),

  -- A real source asset can never be related directly to a fictional asset in a decision.
  CONSTRAINT real_never_relates_to_fictional CHECK (
    NOT (subject_type = 'SOURCE_ASSET' AND object_type = 'ASSET')
    AND NOT (subject_type = 'ASSET' AND object_type = 'SOURCE_ASSET')
  ),
  CONSTRAINT identity_never_involves_fictional CHECK (
    relationship_type <> 'SAME_AS' OR (subject_type <> 'ASSET' AND object_type IS DISTINCT FROM 'ASSET')
  ),
  -- Identity comes from an authoritative identifier or a reviewer citing one, and nothing else.
  CONSTRAINT verified_identity_needs_identifier CHECK (
    NOT (relationship_type IN ('SAME_AS', 'COMPLETION_OF') AND verification_status = 'VERIFIED')
    OR method IN ('AUTHORITATIVE_IDENTIFIER', 'HUMAN_REVIEW')
  ),
  CONSTRAINT weak_methods_cannot_assert_identity CHECK (
    NOT (relationship_type = 'SAME_AS' AND method IN ('NAME_SIMILARITY', 'GEOSPATIAL_PROXIMITY', 'UNIT_SIMILARITY')
         AND verification_status <> 'REJECTED')
  ),
  CONSTRAINT reviewed_identity_cites_identifier CHECK (
    NOT (relationship_type = 'SAME_AS' AND method = 'HUMAN_REVIEW' AND verification_status = 'VERIFIED')
    OR evidence ? 'authoritative_identifier'
  ),
  -- Inferred and verified are mutually exclusive, so they can always be told apart.
  CONSTRAINT inferred_is_never_verified CHECK (provenance_class <> 'INFERRED' OR verification_status <> 'VERIFIED'),
  -- Proximity is a candidate. It is never verified and never states an identity.
  CONSTRAINT proximity_is_only_a_candidate CHECK (
    relationship_type NOT IN ('PROXIMITY_CANDIDATE', 'EMISSION_NEAR')
    OR (
      provenance_class = 'INFERRED' AND verification_status <> 'VERIFIED'
      AND (method = 'GEOSPATIAL_PROXIMITY' OR (method = 'HUMAN_REVIEW' AND verification_status = 'REJECTED'))
    )
  ),
  CONSTRAINT verified_measurement_needs_declared_basis CHECK (
    NOT (relationship_type = 'SAME_MEASUREMENT' AND verification_status = 'VERIFIED')
    OR method IN ('PUBLISHED_DEFINITION_SAME_CLASS', 'DECLARED_SYNTHETIC_DESIGN')
  ),
  -- An experimental assignment is declared, synthetic or replayed, and never verified as real.
  CONSTRAINT experimental_is_never_verified CHECK (
    relationship_type <> 'EXPERIMENTAL_ASSIGNMENT'
    OR (provenance_class IN ('REPLAYED', 'SYNTHETIC') AND verification_status <> 'VERIFIED' AND object_type = 'ASSET')
  ),
  CONSTRAINT review_decisions_are_linked CHECK (
    (method = 'HUMAN_REVIEW') = (review_id IS NOT NULL)
    AND (method <> 'HUMAN_REVIEW' OR supersedes_decision_id IS NOT NULL)
  )
);
COMMENT ON TABLE reconciliation_decisions IS 'Every reconciliation outcome with its identifiers, method, evidence, status, algorithm version, and time. Unknown stays UNRESOLVED.';
COMMENT ON COLUMN reconciliation_decisions.confidence IS 'Only where justified. Distance is not a probability, so proximity candidates leave this NULL.';
CREATE INDEX reconciliation_subject_idx ON reconciliation_decisions (subject_type, subject_id);
CREATE INDEX reconciliation_status_idx ON reconciliation_decisions (module, verification_status);

CREATE TABLE reconciliation_reviews (
  review_id   bigserial PRIMARY KEY,
  decision_id bigint NOT NULL REFERENCES reconciliation_decisions,
  reviewer    text NOT NULL CHECK (reviewer <> ''),
  action      text NOT NULL CHECK (action IN ('APPROVE', 'REJECT', 'REQUEST_EVIDENCE')),
  rationale   text NOT NULL CHECK (length(rationale) >= 10),
  evidence    jsonb NOT NULL DEFAULT '{}',
  reviewed_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE reconciliation_reviews IS 'Human review of a decision. No automatic process writes here.';

ALTER TABLE reconciliation_decisions
  ADD CONSTRAINT decision_review_fk FOREIGN KEY (review_id) REFERENCES reconciliation_reviews;

CREATE TRIGGER reconciliation_decisions_append_only BEFORE UPDATE OR DELETE ON reconciliation_decisions
  FOR EACH ROW EXECUTE FUNCTION reject_change();
CREATE TRIGGER reconciliation_reviews_append_only BEFORE UPDATE OR DELETE ON reconciliation_reviews
  FOR EACH ROW EXECUTE FUNCTION reject_change();

CREATE VIEW v_current_reconciliation_decisions AS
SELECT d.*
FROM reconciliation_decisions d
WHERE NOT EXISTS (
  SELECT 1 FROM reconciliation_decisions later WHERE later.supersedes_decision_id = d.decision_id
);
COMMENT ON VIEW v_current_reconciliation_decisions IS 'Decisions not yet superseded by a reviewed decision.';

CREATE VIEW v_reconciliation_review_queue AS
SELECT d.decision_id, d.module, d.relationship_type, d.subject_id, d.object_id, d.method, d.verification_status, d.decided_at
FROM v_current_reconciliation_decisions d
WHERE d.verification_status IN ('UNVERIFIED', 'UNRESOLVED')
  AND d.relationship_type <> 'EXPERIMENTAL_ASSIGNMENT'
  AND NOT EXISTS (SELECT 1 FROM reconciliation_reviews r WHERE r.decision_id = d.decision_id);
COMMENT ON VIEW v_reconciliation_review_queue IS 'Open decisions awaiting human review. Nothing leaves this queue automatically.';
