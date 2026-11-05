-- Close two gaps found while verifying the Gate 3 merge conditions (ADR 0015).
-- 1. An application must not hold the privileges that can bypass the domain boundary.
-- 2. Every synthetic observation must have a complete, consistent simulation provenance chain.

-- Roles belong to the cluster, so this tolerates a second database on the same server.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fieldtwin_app') THEN
    CREATE ROLE fieldtwin_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO PUBLIC;
GRANT USAGE ON SCHEMA public TO fieldtwin_app;

-- Read everything. Write only the human workflow tables. Source data, scenarios, boundaries, rules,
-- assessments, and transformations are written by the owner in pipelines, never by the application.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO fieldtwin_app;
GRANT INSERT ON work_orders, approval_events, audit_events, inspection_observations,
  anomaly_predictions, reconciliation_reviews, reconciliation_decisions TO fieldtwin_app;
GRANT UPDATE (status) ON work_orders TO fieldtwin_app;
GRANT USAGE ON SEQUENCE work_orders_work_order_id_seq, approval_events_approval_id_seq,
  audit_events_event_id_seq, inspection_observations_inspection_id_seq,
  anomaly_predictions_prediction_id_seq, reconciliation_reviews_review_id_seq,
  reconciliation_decisions_decision_id_seq TO fieldtwin_app;
-- A table added later is readable only, until a migration grants more.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO fieldtwin_app;

COMMENT ON ROLE fieldtwin_app IS 'Least-privilege application role. It cannot edit boundaries, disable triggers, or write source or scenario data. Gate 8 must connect the application through it.';

-- Every synthetic sensor is installed on one fictional asset.
ALTER TABLE sensor_tags ADD COLUMN fictional_asset_id text REFERENCES assets;
UPDATE sensor_tags SET fictional_asset_id = split_part(native_tag_name, '.', 1)
  WHERE source_system_id = 'aether_synthetic';
ALTER TABLE sensor_tags ADD CONSTRAINT synthetic_sensor_has_fictional_asset CHECK (
  (source_system_id = 'aether_synthetic') = (fictional_asset_id IS NOT NULL)
);
COMMENT ON COLUMN sensor_tags.fictional_asset_id IS 'The fictional asset a synthetic sensor is installed on. Always NULL for source tags.';

-- An observation's scenario must be its run's scenario.
ALTER TABLE scenario_runs ADD CONSTRAINT scenario_run_scenario_unique UNIQUE (scenario_run_id, scenario_id);
ALTER TABLE observations ADD CONSTRAINT observation_run_scenario_fk
  FOREIGN KEY (scenario_run_id, scenario_id) REFERENCES scenario_runs (scenario_run_id, scenario_id);

-- A synthetic observation can't exist outside a run, or without a sensor.
ALTER TABLE observations ADD CONSTRAINT synthetic_source_requires_run CHECK (
  (source_system_id = 'aether_synthetic') = (scenario_run_id IS NOT NULL)
);
ALTER TABLE observations ADD CONSTRAINT synthetic_source_requires_sensor CHECK (
  source_system_id <> 'aether_synthetic' OR sensor_tag_id IS NOT NULL
);

CREATE FUNCTION enforce_observation_sensor_source() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  tag_system text;
BEGIN
  IF NEW.sensor_tag_id IS NOT NULL THEN
    SELECT source_system_id INTO tag_system FROM sensor_tags WHERE tag_id = NEW.sensor_tag_id;
    IF tag_system IS DISTINCT FROM NEW.source_system_id THEN
      RAISE EXCEPTION 'observation from % cannot use a sensor from %', NEW.source_system_id, tag_system
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER observation_sensor_source_guard BEFORE INSERT OR UPDATE ON observations
  FOR EACH ROW EXECUTE FUNCTION enforce_observation_sensor_source();

-- A link to a fictional asset must name the asset the sensor is on, and the observation's scenario.
CREATE FUNCTION enforce_fictional_link_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  sensor_asset text;
  observation_scenario text;
BEGIN
  IF NEW.asset_id IS NOT NULL THEN
    SELECT t.fictional_asset_id, o.scenario_id INTO sensor_asset, observation_scenario
      FROM observations o LEFT JOIN sensor_tags t ON t.tag_id = o.sensor_tag_id
      WHERE o.observation_id = NEW.observation_id;
    IF sensor_asset IS DISTINCT FROM NEW.asset_id THEN
      RAISE EXCEPTION 'link names asset %, but the sensor is on %', NEW.asset_id, sensor_asset
        USING ERRCODE = 'check_violation';
    END IF;
    IF observation_scenario IS DISTINCT FROM NEW.scenario_id THEN
      RAISE EXCEPTION 'link names scenario %, but the observation belongs to %', NEW.scenario_id, observation_scenario
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER fictional_link_chain_guard BEFORE INSERT OR UPDATE ON asset_observation_links
  FOR EACH ROW EXECUTE FUNCTION enforce_fictional_link_chain();

CREATE VIEW v_synthetic_provenance_chain AS
SELECT
  o.observation_id,
  o.source_record_id,
  o.provenance_class,
  o.sensor_tag_id,
  t.fictional_asset_id AS asset_id,
  a.is_fictional AS asset_is_fictional,
  l.asset_id AS linked_asset_id,
  l.relationship_type AS link_type,
  o.scenario_id,
  s.scenario_version,
  o.scenario_run_id,
  r.simulator_name,
  r.simulator_version,
  r.config_sha256 AS parameter_set_sha256,
  r.random_seed,
  r.output_sha256,
  o.transformation_id,
  tr.output_provenance,
  (
    o.provenance_class = 'SYNTHETIC' AND tr.output_provenance = 'SYNTHETIC' AND a.is_fictional
    AND l.asset_id = t.fictional_asset_id AND l.relationship_type = 'EXPERIMENTAL_SCENARIO_LINK'
    AND r.scenario_id = o.scenario_id AND r.simulator_version IS NOT NULL
    AND r.config_sha256 IS NOT NULL AND r.output_sha256 IS NOT NULL
  ) IS TRUE AS chain_complete
FROM observations o
LEFT JOIN sensor_tags t ON t.tag_id = o.sensor_tag_id
LEFT JOIN assets a ON a.asset_id = t.fictional_asset_id
LEFT JOIN asset_observation_links l ON l.observation_id = o.observation_id AND l.asset_id IS NOT NULL
LEFT JOIN scenario_runs r ON r.scenario_run_id = o.scenario_run_id
LEFT JOIN scenarios s ON s.scenario_id = o.scenario_id
LEFT JOIN transformations tr ON tr.transformation_id = o.transformation_id
WHERE o.source_system_id = 'aether_synthetic';
COMMENT ON VIEW v_synthetic_provenance_chain IS 'Each synthetic observation with its asset, sensor, scenario, run, simulator version, and parameter set.';
