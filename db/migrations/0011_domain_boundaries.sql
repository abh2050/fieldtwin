-- Physical-system boundaries and equipment relationship rules (ADRs 0010 and 0014).
-- These add restrictions. No earlier constraint is loosened.

CREATE TABLE domain_boundaries (
  source_system_id text NOT NULL REFERENCES source_systems,
  target_domain    text NOT NULL CHECK (target_domain IN ('REAL_ONSHORE', 'REAL_OFFSHORE', 'FICTIONAL_ONSHORE')),
  is_allowed       boolean NOT NULL,
  rationale        text NOT NULL,
  PRIMARY KEY (source_system_id, target_domain)
);
COMMENT ON TABLE domain_boundaries IS 'Whether a source may be mapped onto a target domain. A missing row means refused.';

-- Fires after scenario_mapping_guard, because triggers run in name order. Default deny.
CREATE FUNCTION enforce_domain_boundary() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  event_system text;
  asset_domain text;
  allowed boolean;
BEGIN
  SELECT source_system_id INTO event_system FROM telemetry_events WHERE event_id = NEW.telemetry_event_id;
  SELECT c.domain INTO asset_domain FROM assets a
    JOIN equipment_classes c ON c.equipment_class_id = a.equipment_class_id
    WHERE a.asset_id = NEW.target_asset_id;
  SELECT b.is_allowed INTO allowed FROM domain_boundaries b
    WHERE b.source_system_id = event_system AND b.target_domain = asset_domain;
  IF allowed IS NOT TRUE THEN
    RAISE EXCEPTION 'domain boundary: % cannot be mapped onto %', event_system, asset_domain
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER scenario_mapping_zz_boundary BEFORE INSERT ON scenario_mappings
  FOR EACH ROW EXECUTE FUNCTION enforce_domain_boundary();

CREATE TABLE equipment_relationship_rules (
  source_asset_type text NOT NULL,
  relationship_type text NOT NULL,
  target_asset_type text NOT NULL,
  rationale         text NOT NULL,
  PRIMARY KEY (source_asset_type, relationship_type, target_asset_type)
);
COMMENT ON TABLE equipment_relationship_rules IS 'The fictional facility''s allowed flow connections. Anything not listed is refused.';

INSERT INTO equipment_relationship_rules VALUES
  ('WELL_PAD', 'FEEDS', 'GATHERING_NETWORK', 'A pad delivers into the gathering network.'),
  ('GATHERING_NETWORK', 'FEEDS', 'COMPRESSOR', 'The network supplies the compressors.'),
  ('WELL', 'FEEDS', 'GATHERING_SEGMENT', 'A well delivers into a gathering segment.'),
  ('GATHERING_SEGMENT', 'FEEDS', 'GATHERING_SEGMENT', 'Segments connect in series toward the trunk.'),
  ('GATHERING_SEGMENT', 'FEEDS', 'COMPRESSION_STATION', 'The trunk delivers to the station.');

CREATE FUNCTION enforce_equipment_relationship() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  source_type text;
  target_type text;
BEGIN
  SELECT asset_type INTO source_type FROM assets WHERE asset_id = NEW.source_asset_id;
  SELECT asset_type INTO target_type FROM assets WHERE asset_id = NEW.target_asset_id;
  IF NOT EXISTS (
    SELECT 1 FROM equipment_relationship_rules r
    WHERE r.source_asset_type = source_type AND r.relationship_type = NEW.relationship_type
      AND r.target_asset_type = target_type
  ) THEN
    RAISE EXCEPTION 'invalid equipment relationship: % % %', source_type, NEW.relationship_type, target_type
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER asset_relationship_rule_guard BEFORE INSERT OR UPDATE ON asset_relationships
  FOR EACH ROW EXECUTE FUNCTION enforce_equipment_relationship();
