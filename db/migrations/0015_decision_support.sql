-- Gate 7: detector alarms, explained recommendations, and work orders with enforced transitions (ADR 0019).
-- Everything here concerns fictional AETHER assets in simulated scenarios. Nothing actuates equipment.

-- A detector alarm start, INFERRED from SYNTHETIC telemetry. It holds no fault truth.
CREATE TABLE detector_alarms (
  alarm_id          text PRIMARY KEY,
  scenario_id       text NOT NULL REFERENCES scenarios,
  scenario_run_id   text NOT NULL REFERENCES scenario_runs,
  started_at        timestamptz NOT NULL,
  score             double precision NOT NULL,
  threshold         double precision NOT NULL,
  model_id          text NOT NULL,
  model_version     text NOT NULL,
  model_sha256      text NOT NULL CHECK (model_sha256 ~ '^[0-9a-f]{64}$'),
  evidence          jsonb NOT NULL CHECK (jsonb_typeof(evidence) = 'array'),
  earlier_starts_in_lookback integer NOT NULL CHECK (earlier_starts_in_lookback >= 0),
  first_alarm_at    timestamptz NOT NULL CHECK (first_alarm_at <= started_at),
  provenance_class  provenance_class NOT NULL CHECK (provenance_class = 'INFERRED'),
  input_provenance  provenance_class NOT NULL CHECK (input_provenance = 'SYNTHETIC'),
  CONSTRAINT alarm_crossed_threshold CHECK (score >= threshold)
);
COMMENT ON TABLE detector_alarms IS 'Alarm starts from the Gate 5 detector on simulated telemetry. A score is never a failure probability.';
CREATE TRIGGER detector_alarms_append_only BEFORE UPDATE OR DELETE ON detector_alarms
  FOR EACH ROW EXECUTE FUNCTION reject_change();

CREATE TABLE recommendations (
  recommendation_id text PRIMARY KEY,
  alarm_id          text NOT NULL REFERENCES detector_alarms,
  scenario_id       text NOT NULL REFERENCES scenarios,
  scenario_run_id   text NOT NULL REFERENCES scenario_runs,
  decided_at        timestamptz NOT NULL,
  action            text NOT NULL CHECK (action IN (
    'FIELD_INSPECTION', 'CHECK_INSTRUMENTATION', 'NO_ACTION_PLANNED_OPERATION', 'NEEDS_EVIDENCE'
  )),
  candidate_assets  text[] NOT NULL,
  suppressed_assets text[] NOT NULL,
  priority_score    integer NOT NULL CHECK (priority_score >= 0),
  priority_band     text CHECK (priority_band IN ('P1', 'P2', 'P3')),
  respond_within_h  integer CHECK (respond_within_h > 0),
  terms             jsonb NOT NULL CHECK (jsonb_typeof(terms) = 'array' AND jsonb_array_length(terms) > 0),
  explanation       jsonb NOT NULL CHECK (jsonb_typeof(explanation) = 'array' AND jsonb_array_length(explanation) > 0),
  rules_version     integer NOT NULL CHECK (rules_version > 0),
  provenance_class  provenance_class NOT NULL CHECK (provenance_class = 'SYNTHETIC'),
  CONSTRAINT dispatch_has_band_and_candidate CHECK (
    (action IN ('FIELD_INSPECTION', 'CHECK_INSTRUMENTATION'))
      = (priority_band IS NOT NULL AND cardinality(candidate_assets) > 0)
  )
);
COMMENT ON TABLE recommendations IS 'Deterministic, explained recommendations. Every score point comes from a stored term.';

CREATE FUNCTION enforce_recommendation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  term_total integer;
  unknown text;
  alarm_run text;
BEGIN
  SELECT coalesce(sum((t->>'points')::integer), -1) INTO term_total FROM jsonb_array_elements(NEW.terms) AS t;
  IF term_total <> NEW.priority_score THEN
    RAISE EXCEPTION 'priority score % is not the sum of its terms (%)', NEW.priority_score, term_total
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT a INTO unknown FROM unnest(NEW.candidate_assets || NEW.suppressed_assets) AS a
    WHERE a NOT IN (SELECT asset_id FROM assets) LIMIT 1;
  IF unknown IS NOT NULL THEN
    RAISE EXCEPTION '% is not a fictional asset', unknown USING ERRCODE = 'check_violation';
  END IF;
  SELECT scenario_run_id INTO alarm_run FROM detector_alarms WHERE alarm_id = NEW.alarm_id;
  IF alarm_run IS DISTINCT FROM NEW.scenario_run_id THEN
    RAISE EXCEPTION 'a recommendation must come from an alarm in its own run' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER recommendation_guard BEFORE INSERT ON recommendations
  FOR EACH ROW EXECUTE FUNCTION enforce_recommendation();
CREATE TRIGGER recommendations_append_only BEFORE UPDATE OR DELETE ON recommendations
  FOR EACH ROW EXECUTE FUNCTION reject_change();

-- Work orders now trace to the recommendation that created them.
ALTER TABLE work_orders ADD COLUMN external_id text UNIQUE;
ALTER TABLE work_orders ADD COLUMN recommendation_id text REFERENCES recommendations;
ALTER TABLE work_orders ADD COLUMN priority_band text CHECK (priority_band IN ('P1', 'P2', 'P3'));

CREATE FUNCTION enforce_work_order_creation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  rec recommendations%ROWTYPE;
BEGIN
  IF NEW.recommendation_id IS NULL THEN
    RETURN NEW;  -- Rows from before Gate 7 keep their original rules.
  END IF;
  SELECT * INTO rec FROM recommendations WHERE recommendation_id = NEW.recommendation_id;
  IF NEW.status <> 'RECOMMENDED' THEN
    RAISE EXCEPTION 'a work order starts as RECOMMENDED' USING ERRCODE = 'check_violation';
  END IF;
  IF rec.action NOT IN ('FIELD_INSPECTION', 'CHECK_INSTRUMENTATION') THEN
    RAISE EXCEPTION 'recommendation % does not dispatch', rec.recommendation_id USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.asset_id IS DISTINCT FROM rec.candidate_assets[1] OR NEW.scenario_id IS DISTINCT FROM rec.scenario_id
     OR NEW.priority IS DISTINCT FROM rec.priority_score OR NEW.priority_band IS DISTINCT FROM rec.priority_band THEN
    RAISE EXCEPTION 'work order must match its recommendation' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER work_order_creation_guard BEFORE INSERT ON work_orders
  FOR EACH ROW EXECUTE FUNCTION enforce_work_order_creation();

-- Every change of status, with who made it. Append-only and checked against the allowed transitions.
CREATE TABLE work_order_transitions (
  transition_id  bigserial PRIMARY KEY,
  work_order_id  bigint NOT NULL REFERENCES work_orders,
  sequence       integer NOT NULL CHECK (sequence >= 0),
  decision       text NOT NULL CHECK (decision IN ('CREATE', 'APPROVE', 'REJECT', 'REQUEST_EVIDENCE', 'RESUBMIT', 'COMPLETE')),
  from_status    text,
  to_status      text NOT NULL,
  actor_id       text NOT NULL CHECK (length(btrim(actor_id)) > 0),
  actor_kind     text NOT NULL CHECK (actor_kind IN ('HUMAN', 'SCRIPTED_DEMO', 'SYSTEM')),
  actor_role     text NOT NULL,
  justification  text NOT NULL CHECK (length(btrim(justification)) > 0),
  -- Scenario clock (simulated time). recorded_at is the real time the row was written.
  decided_at     timestamptz NOT NULL,
  recorded_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (work_order_id, sequence),
  CONSTRAINT allowed_transition CHECK (
    (decision, coalesce(from_status, '-'), to_status) IN (
      ('CREATE', '-', 'RECOMMENDED'),
      ('APPROVE', 'RECOMMENDED', 'APPROVED'),
      ('REJECT', 'RECOMMENDED', 'REJECTED'),
      ('REQUEST_EVIDENCE', 'RECOMMENDED', 'NEEDS_EVIDENCE'),
      ('RESUBMIT', 'NEEDS_EVIDENCE', 'RECOMMENDED'),
      ('REJECT', 'NEEDS_EVIDENCE', 'REJECTED'),
      ('COMPLETE', 'APPROVED', 'COMPLETED')
    )
  ),
  -- The engine creates and nothing else; nobody else creates.
  CONSTRAINT only_the_engine_creates CHECK ((decision = 'CREATE') = (actor_kind = 'SYSTEM')),
  CONSTRAINT supervisor_decides CHECK (
    decision NOT IN ('APPROVE', 'REJECT', 'REQUEST_EVIDENCE') OR actor_role = 'MAINTENANCE_SUPERVISOR'
  )
);
COMMENT ON TABLE work_order_transitions IS 'Authoritative work-order history. SCRIPTED_DEMO actors stand in for people in demonstration runs and are never human decisions.';
CREATE TRIGGER work_order_transitions_append_only BEFORE UPDATE OR DELETE ON work_order_transitions
  FOR EACH ROW EXECUTE FUNCTION reject_change();

CREATE FUNCTION enforce_transition_order() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  current_status text;
  recorded integer;
  previous timestamptz;
BEGIN
  SELECT status INTO current_status FROM work_orders WHERE work_order_id = NEW.work_order_id;
  SELECT count(*), max(decided_at) INTO recorded, previous FROM work_order_transitions WHERE work_order_id = NEW.work_order_id;
  IF NEW.sequence <> recorded THEN
    RAISE EXCEPTION 'transition % is out of sequence (expected %)', NEW.sequence, recorded USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.decision <> 'CREATE' AND NEW.from_status IS DISTINCT FROM current_status THEN
    RAISE EXCEPTION 'work order is %, not %', current_status, NEW.from_status USING ERRCODE = 'check_violation';
  END IF;
  IF previous IS NOT NULL AND NEW.decided_at < previous THEN
    RAISE EXCEPTION 'transitions must be recorded in time order' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER work_order_transition_order BEFORE INSERT ON work_order_transitions
  FOR EACH ROW EXECUTE FUNCTION enforce_transition_order();

-- A status may change only to match the latest recorded transition, with an audit event for it.
CREATE FUNCTION enforce_status_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  latest work_order_transitions%ROWTYPE;
BEGIN
  IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
    RETURN NEW;
  END IF;
  SELECT * INTO latest FROM work_order_transitions WHERE work_order_id = NEW.work_order_id
    ORDER BY sequence DESC LIMIT 1;
  IF latest.transition_id IS NULL OR latest.from_status IS DISTINCT FROM OLD.status OR latest.to_status <> NEW.status THEN
    RAISE EXCEPTION 'status change % to % has no matching transition', OLD.status, NEW.status
      USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM audit_events WHERE correlation_id = 'transition:' || latest.transition_id) THEN
    RAISE EXCEPTION 'status change has no audit event' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER work_order_status_guard BEFORE UPDATE OF status ON work_orders
  FOR EACH ROW EXECUTE FUNCTION enforce_status_change();

-- Supervisor decisions are also kept in approval_events, now with who made them.
ALTER TABLE approval_events ADD COLUMN actor_kind text CHECK (actor_kind IN ('HUMAN', 'SCRIPTED_DEMO'));
ALTER TABLE approval_events ADD COLUMN actor_role text;

-- The application records transitions, approvals, and audit events; it never writes alarms or recommendations.
GRANT INSERT ON work_order_transitions TO fieldtwin_app;
GRANT USAGE ON SEQUENCE work_order_transitions_transition_id_seq TO fieldtwin_app;
