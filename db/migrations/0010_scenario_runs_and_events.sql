-- Synthetic scenario runs and the shared event contract (ADR 0012).

CREATE TABLE scenario_runs (
  scenario_run_id  text PRIMARY KEY,
  scenario_id      text NOT NULL REFERENCES scenarios,
  case_name        text NOT NULL CHECK (case_name IN ('nominal', 'fault')),
  target_asset_id  text NOT NULL REFERENCES assets,
  affected_asset_id text NOT NULL REFERENCES assets,
  simulator_name   text NOT NULL,
  simulator_version integer NOT NULL CHECK (simulator_version > 0),
  config_sha256    text NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
  output_sha256    text NOT NULL CHECK (output_sha256 ~ '^[0-9a-f]{64}$'),
  output_uri       text NOT NULL,
  random_seed      bigint NOT NULL,
  sample_count     integer NOT NULL CHECK (sample_count > 0),
  sampling_interval_s integer NOT NULL CHECK (sampling_interval_s > 0),
  fault_onset_offset_s integer,
  parameters       jsonb NOT NULL,
  invariants       jsonb NOT NULL,
  provenance_class provenance_class NOT NULL CHECK (provenance_class = 'SYNTHETIC'),
  transformation_id text NOT NULL,
  UNIQUE (scenario_id, case_name),
  FOREIGN KEY (transformation_id, provenance_class) REFERENCES transformations (transformation_id, output_provenance),
  CONSTRAINT fault_case_has_known_onset CHECK ((case_name = 'fault') = (fault_onset_offset_s IS NOT NULL))
);
COMMENT ON TABLE scenario_runs IS 'One simulator run on fictional assets, with its parameters, seed, and output checksum. Always SYNTHETIC, and immutable.';
CREATE TRIGGER scenario_runs_immutable BEFORE UPDATE OR DELETE ON scenario_runs
  FOR EACH ROW EXECUTE FUNCTION reject_change();

ALTER TABLE observations ADD COLUMN scenario_run_id text REFERENCES scenario_runs;
ALTER TABLE observations ADD CONSTRAINT simulated_series_is_synthetic CHECK (
  scenario_run_id IS NULL OR (provenance_class = 'SYNTHETIC' AND scenario_id IS NOT NULL)
);

CREATE TABLE shared_events (
  event_id         text PRIMARY KEY,
  schema_version   integer NOT NULL CHECK (schema_version > 0),
  domain           text NOT NULL CHECK (domain IN ('AETHER_SYNTHETIC', 'OFFSHORE_BENCHMARK')),
  event_kind       text NOT NULL CHECK (event_kind IN ('SOURCE_LABEL', 'KNOWN_SYNTHETIC_ONSET', 'INTEGRATION_PROOF_RULE')),
  event_class      text NOT NULL,
  source_system_id text NOT NULL REFERENCES source_systems,
  telemetry_event_id text REFERENCES telemetry_events,
  scenario_id      text REFERENCES scenarios,
  scenario_run_id  text REFERENCES scenario_runs,
  target_asset_id  text REFERENCES assets,
  affected_asset_id text REFERENCES assets,
  onset_offset_s   integer CHECK (onset_offset_s >= 0),
  evidence         jsonb NOT NULL CHECK (evidence <> '{}'::jsonb),
  provenance_class provenance_class NOT NULL,
  transformation_id text NOT NULL,
  FOREIGN KEY (transformation_id, provenance_class) REFERENCES transformations (transformation_id, output_provenance),
  CONSTRAINT aether_events_are_synthetic_and_scoped CHECK (
    domain <> 'AETHER_SYNTHETIC' OR (
      provenance_class = 'SYNTHETIC' AND source_system_id = 'aether_synthetic'
      AND scenario_id IS NOT NULL AND scenario_run_id IS NOT NULL AND target_asset_id IS NOT NULL
      AND telemetry_event_id IS NULL AND event_kind <> 'SOURCE_LABEL'
    )
  ),
  -- A benchmark event carries its source identity and can never name an AETHER asset.
  CONSTRAINT benchmark_events_stay_independent CHECK (
    domain <> 'OFFSHORE_BENCHMARK' OR (
      provenance_class IN ('DERIVED', 'SYNTHETIC') AND source_system_id = 'petrobras_3w'
      AND telemetry_event_id IS NOT NULL AND event_kind = 'SOURCE_LABEL'
      AND scenario_id IS NULL AND scenario_run_id IS NULL
      AND target_asset_id IS NULL AND affected_asset_id IS NULL
    )
  )
);
COMMENT ON TABLE shared_events IS 'One event contract for both domains, which stay separate. It carries no detection accuracy.';
CREATE INDEX shared_events_domain_idx ON shared_events (domain, event_class);

-- A benchmark event's class must follow its instance's origin.
CREATE FUNCTION enforce_benchmark_event_origin() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  origin instance_origin;
BEGIN
  IF NEW.domain = 'OFFSHORE_BENCHMARK' THEN
    SELECT real_or_simulated_source INTO origin FROM telemetry_events WHERE event_id = NEW.telemetry_event_id;
    IF (origin = 'REAL') <> (NEW.provenance_class = 'DERIVED') THEN
      RAISE EXCEPTION 'benchmark event from a % instance cannot be %', origin, NEW.provenance_class
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER shared_event_origin_guard BEFORE INSERT OR UPDATE ON shared_events
  FOR EACH ROW EXECUTE FUNCTION enforce_benchmark_event_origin();
CREATE TRIGGER shared_events_immutable BEFORE UPDATE OR DELETE ON shared_events
  FOR EACH ROW EXECUTE FUNCTION reject_change();
