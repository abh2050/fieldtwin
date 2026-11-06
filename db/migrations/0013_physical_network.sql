-- Physical connectivity of the fictional facility as a typed directed graph (ADR 0016).
-- It is separate from asset_relationships, reconciliation decisions, and identity records.

CREATE TABLE physical_nodes (
  node_id         text PRIMARY KEY,
  facility_id     text NOT NULL REFERENCES facilities,
  node_type       text NOT NULL CHECK (node_type IN (
    'RESERVOIR_BOUNDARY', 'WELLHEAD', 'JUNCTION', 'MANIFOLD', 'SUCTION_HEADER', 'DISCHARGE_BOUNDARY', 'SITE'
  )),
  asset_id        text NOT NULL REFERENCES assets,
  local_x_m       double precision,
  local_y_m       double precision,
  network_version integer NOT NULL CHECK (network_version > 0),
  provenance_class provenance_class NOT NULL CHECK (provenance_class = 'SYNTHETIC'),
  CONSTRAINT coordinates_together CHECK ((local_x_m IS NULL) = (local_y_m IS NULL))
);
COMMENT ON TABLE physical_nodes IS 'Places where pressure is defined, or fictional sites. Local metres from a fictional origin, so no real location is implied.';

CREATE TABLE physical_edges (
  edge_id         text PRIMARY KEY,
  edge_type       text NOT NULL CHECK (edge_type IN (
    'WELL_INFLOW', 'FLOWLINE', 'GATHERING_SEGMENT', 'COMPRESSION', 'ACCESS_ROUTE'
  )),
  from_node_id    text NOT NULL REFERENCES physical_nodes,
  to_node_id      text NOT NULL REFERENCES physical_nodes,
  element_asset_id text NOT NULL REFERENCES assets,
  valve_asset_id  text REFERENCES assets,
  length_m        double precision CHECK (length_m > 0),
  diameter_m      double precision CHECK (diameter_m > 0),
  network_version integer NOT NULL CHECK (network_version > 0),
  provenance_class provenance_class NOT NULL CHECK (provenance_class = 'SYNTHETIC'),
  CONSTRAINT edge_not_self CHECK (from_node_id <> to_node_id),
  CONSTRAINT pipes_have_geometry CHECK (
    edge_type NOT IN ('FLOWLINE', 'GATHERING_SEGMENT') OR (length_m IS NOT NULL AND diameter_m IS NOT NULL)
  )
);
COMMENT ON TABLE physical_edges IS 'Directed connections. A closed valve or stopped machine is a run state, so this graph stays fixed.';
CREATE INDEX physical_edges_from_idx ON physical_edges (from_node_id);
CREATE INDEX physical_edges_to_idx ON physical_edges (to_node_id);

CREATE TABLE physical_connection_rules (
  edge_type      text NOT NULL,
  from_node_type text NOT NULL,
  to_node_type   text NOT NULL,
  PRIMARY KEY (edge_type, from_node_type, to_node_type)
);
COMMENT ON TABLE physical_connection_rules IS 'Allowed physical connections. Anything not listed is refused.';

INSERT INTO physical_connection_rules VALUES
  ('WELL_INFLOW', 'RESERVOIR_BOUNDARY', 'WELLHEAD'),
  ('FLOWLINE', 'WELLHEAD', 'JUNCTION'),
  ('GATHERING_SEGMENT', 'JUNCTION', 'MANIFOLD'),
  ('GATHERING_SEGMENT', 'MANIFOLD', 'SUCTION_HEADER'),
  ('COMPRESSION', 'SUCTION_HEADER', 'DISCHARGE_BOUNDARY'),
  ('ACCESS_ROUTE', 'SITE', 'SITE'),
  ('ACCESS_ROUTE', 'SITE', 'JUNCTION'),
  ('ACCESS_ROUTE', 'SITE', 'SUCTION_HEADER');

CREATE FUNCTION enforce_physical_connection() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  from_type text;
  to_type text;
BEGIN
  SELECT node_type INTO from_type FROM physical_nodes WHERE node_id = NEW.from_node_id;
  SELECT node_type INTO to_type FROM physical_nodes WHERE node_id = NEW.to_node_id;
  IF NOT EXISTS (
    SELECT 1 FROM physical_connection_rules r
    WHERE r.edge_type = NEW.edge_type AND r.from_node_type = from_type AND r.to_node_type = to_type
  ) THEN
    RAISE EXCEPTION 'invalid physical connection: % from % to %', NEW.edge_type, from_type, to_type
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER physical_edge_rule_guard BEFORE INSERT OR UPDATE ON physical_edges
  FOR EACH ROW EXECUTE FUNCTION enforce_physical_connection();
