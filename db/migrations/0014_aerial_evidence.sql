-- Gate 6: aerial evidence review and inspection requests (ADR 0018).
-- Real plumes and images link to real registry wells only, as proximity or coverage. Requests target
-- fictional assets only, from synthetic scenario events. Neither table can express source attribution.

-- Human review of a plume or an image. Append-only; a correction is a new row that supersedes one.
-- Reviews are always blind to plume status, and hold no free text: outcome and visible features come
-- from fixed vocabularies, so nothing displayed from a review can assert a leak, a source, or a defect.
CREATE TABLE inspection_review_events (
  review_id      text PRIMARY KEY,
  evidence_id    text NOT NULL,
  evidence_kind  text NOT NULL CHECK (evidence_kind IN ('NAIP_CHIP', 'PLUME')),
  observation_id bigint NOT NULL REFERENCES observations,
  reviewer       text NOT NULL CHECK (length(btrim(reviewer)) > 0),
  outcome        text NOT NULL CHECK (outcome IN (
    'NO_FEATURE_OF_NOTE', 'INFRASTRUCTURE_VISIBLE', 'IMAGE_UNUSABLE', 'FIELD_VERIFICATION_SUGGESTED'
  )),
  visible_features text[] NOT NULL DEFAULT '{}' CHECK (visible_features <@ ARRAY[
    'WELL_PAD', 'WELLHEAD_EQUIPMENT', 'TANK_BATTERY', 'COMPRESSION_EQUIPMENT', 'FLARE_STACK',
    'PIT_OR_POND', 'PIPELINE_CORRIDOR', 'OTHER_STRUCTURE', 'CLOUD_OR_SHADOW', 'IMAGE_ARTIFACT'
  ]::text[]),
  blinded_to_plume_status boolean NOT NULL CHECK (blinded_to_plume_status),
  supersedes     text REFERENCES inspection_review_events,
  recorded_at    timestamptz NOT NULL,
  provenance_class provenance_class NOT NULL CHECK (provenance_class = 'OBSERVED')
);
COMMENT ON TABLE inspection_review_events IS 'Reviewer findings on real aerial evidence. No outcome confirms a leak or names a source.';
CREATE UNIQUE INDEX review_superseded_once ON inspection_review_events (supersedes) WHERE supersedes IS NOT NULL;
CREATE INDEX review_evidence_idx ON inspection_review_events (evidence_id);
CREATE TRIGGER inspection_review_events_append_only BEFORE UPDATE OR DELETE ON inspection_review_events
  FOR EACH ROW EXECUTE FUNCTION reject_change();

CREATE FUNCTION enforce_review_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  observation_system text;
  previous_evidence text;
BEGIN
  SELECT source_system_id INTO observation_system FROM observations WHERE observation_id = NEW.observation_id;
  IF observation_system NOT IN ('carbon_mapper', 'naip') THEN
    RAISE EXCEPTION 'reviews cover aerial evidence only, not %', observation_system USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.supersedes IS NOT NULL THEN
    SELECT evidence_id INTO previous_evidence FROM inspection_review_events WHERE review_id = NEW.supersedes;
    IF previous_evidence IS DISTINCT FROM NEW.evidence_id THEN
      RAISE EXCEPTION 'a review can only supersede a review of the same evidence' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER inspection_review_chain BEFORE INSERT ON inspection_review_events
  FOR EACH ROW EXECUTE FUNCTION enforce_review_chain();

-- Requests reference `assets`, which holds fictional assets only, so a real well can't be targeted.
CREATE TABLE inspection_requests (
  request_id        text PRIMARY KEY,
  asset_id          text NOT NULL REFERENCES assets,
  affected_asset_id text NOT NULL REFERENCES assets,
  scenario_id       text NOT NULL REFERENCES scenarios,
  scenario_run_id   text NOT NULL REFERENCES scenario_runs,
  trigger_event_id  text NOT NULL REFERENCES shared_events,
  inspection_type   text NOT NULL CHECK (inspection_type IN ('GROUND_INSPECTION', 'AERIAL_SURVEY')),
  reason            text NOT NULL,
  status            text NOT NULL CHECK (status IN ('REQUESTED', 'CANCELLED', 'COMPLETED')),
  created_at        timestamptz NOT NULL,
  provenance_class  provenance_class NOT NULL CHECK (provenance_class = 'SYNTHETIC')
);
COMMENT ON TABLE inspection_requests IS 'Simulated inspection requests on fictional assets. No priority score; Gate 7 owns prioritization.';

CREATE FUNCTION enforce_request_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  event_domain text;
  event_run text;
BEGIN
  SELECT domain, scenario_run_id INTO event_domain, event_run FROM shared_events WHERE event_id = NEW.trigger_event_id;
  IF event_domain IS DISTINCT FROM 'AETHER_SYNTHETIC' OR event_run IS DISTINCT FROM NEW.scenario_run_id THEN
    RAISE EXCEPTION 'inspection requests come only from synthetic AETHER events of the same run'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER inspection_request_trigger_guard BEFORE INSERT OR UPDATE ON inspection_requests
  FOR EACH ROW EXECUTE FUNCTION enforce_request_trigger();

-- The application records reviews and requests; it never writes source data.
GRANT INSERT ON inspection_review_events, inspection_requests TO fieldtwin_app;
GRANT UPDATE (status) ON inspection_requests TO fieldtwin_app;
