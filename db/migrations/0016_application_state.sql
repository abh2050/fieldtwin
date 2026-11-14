-- Gate 8: the only state the application owns (ADR 0021). Replay sessions over stored simulator
-- output, and idempotency records for state-changing requests. Neither creates telemetry, alarms,
-- recommendations, or results; the application can still write only the human workflow tables.

-- Where a person is in replaying a stored scenario run. A replay reads the run's stored output up to
-- this position; it never simulates anything new.
CREATE TABLE scenario_replays (
  scenario_id      text PRIMARY KEY REFERENCES scenarios,
  scenario_run_id  text NOT NULL REFERENCES scenario_runs,
  state            text NOT NULL CHECK (state IN ('PLAYING', 'PAUSED', 'STOPPED')),
  -- Position on the run's clock when the state last changed, in seconds from the run's start.
  position_s       integer NOT NULL CHECK (position_s >= 0),
  -- Simulated seconds per real second while PLAYING.
  speed            double precision NOT NULL CHECK (speed > 0 AND speed <= 3600),
  -- Real time the position was recorded; a PLAYING position advances from here.
  anchored_at      timestamptz NOT NULL DEFAULT now(),
  updated_by       text NOT NULL CHECK (length(btrim(updated_by)) > 0),
  CONSTRAINT replay_run_belongs_to_scenario CHECK (split_part(scenario_run_id, ':', 1) = scenario_id)
);
COMMENT ON TABLE scenario_replays IS 'Replay cursor over stored simulator output. Replaying generates no data.';

-- A state-changing request repeated with the same key gets the first response back, not a second effect.
CREATE TABLE api_idempotency_keys (
  actor_id         text NOT NULL,
  idempotency_key  text NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{8,128}$'),
  method           text NOT NULL,
  path             text NOT NULL,
  request_sha256   text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  status_code      integer NOT NULL CHECK (status_code BETWEEN 200 AND 299),
  response         jsonb NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (actor_id, idempotency_key)
);
COMMENT ON TABLE api_idempotency_keys IS 'Successful responses to state-changing requests, keyed by caller and Idempotency-Key.';
CREATE TRIGGER api_idempotency_keys_append_only BEFORE UPDATE OR DELETE ON api_idempotency_keys
  FOR EACH ROW EXECUTE FUNCTION reject_change();

GRANT SELECT, INSERT, UPDATE ON scenario_replays TO fieldtwin_app;
GRANT SELECT, INSERT ON api_idempotency_keys TO fieldtwin_app;
