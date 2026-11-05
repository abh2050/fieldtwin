-- Domain compatibility, experimental scenarios, and the boundary around them (ADRs 0008 and 0010).

CREATE TABLE domain_compatibility_requirements (
  requirement_id     text PRIMARY KEY,
  target_equipment_class_id text NOT NULL REFERENCES equipment_classes,
  category           text NOT NULL,
  requirement        text NOT NULL,
  target_value       text NOT NULL,
  rationale          text NOT NULL
);
COMMENT ON TABLE domain_compatibility_requirements IS 'Equipment and operating conditions that telemetry must meet before it can be applied to an experimental asset.';

CREATE TABLE domain_compatibility_assessments (
  assessment_id      text PRIMARY KEY,
  source_system_id   text NOT NULL REFERENCES source_systems,
  subject_type       text NOT NULL CHECK (subject_type IN ('VARIABLE', 'EVENT_CLASS')),
  subject_id         text NOT NULL,
  target_equipment_class_id text NOT NULL REFERENCES equipment_classes,
  classification     compatibility_class NOT NULL,
  reasoning          text NOT NULL,
  conditions         jsonb NOT NULL DEFAULT '[]',
  assessment_version integer NOT NULL,
  assessed_on        date NOT NULL,
  UNIQUE (source_system_id, subject_type, subject_id, target_equipment_class_id, assessment_version),
  CONSTRAINT conditional_states_conditions CHECK (
    classification <> 'CONDITIONALLY_COMPATIBLE' OR jsonb_array_length(conditions) > 0
  )
);
COMMENT ON TABLE domain_compatibility_assessments IS 'Engineering judgment, versioned. Not field validation. Generated from data_contracts/semantic_mappings/3w_aether_compatibility.yaml.';

CREATE TABLE scenarios (
  scenario_id        text PRIMARY KEY,
  scenario_name      text NOT NULL,
  scenario_description text NOT NULL,
  target_facility_id text NOT NULL REFERENCES facilities,
  scenario_version   integer NOT NULL CHECK (scenario_version > 0),
  random_seed        bigint NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE observations ADD CONSTRAINT observation_scenario_fk FOREIGN KEY (scenario_id) REFERENCES scenarios;

CREATE TABLE scenario_mappings (
  mapping_id         bigserial PRIMARY KEY,
  scenario_id        text NOT NULL REFERENCES scenarios,
  target_asset_id    text NOT NULL REFERENCES assets,
  telemetry_event_id text NOT NULL,
  original_source_instance_id text NOT NULL,
  transformation_config jsonb NOT NULL,
  compatibility_assessment_id text NOT NULL REFERENCES domain_compatibility_assessments,
  conditions_satisfied jsonb,
  mapping_provenance provenance_class NOT NULL CHECK (mapping_provenance IN ('REPLAYED', 'SYNTHETIC')),
  replay_start_time  timestamptz,
  UNIQUE (scenario_id, target_asset_id, telemetry_event_id),
  FOREIGN KEY (telemetry_event_id, original_source_instance_id) REFERENCES telemetry_events (event_id, source_instance_id)
);
COMMENT ON TABLE scenario_mappings IS 'Explicit, immutable experimental association. Never OBSERVED, and a new version means a new row.';

CREATE FUNCTION enforce_scenario_mapping() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  assessment domain_compatibility_assessments%ROWTYPE;
  event_row  telemetry_events%ROWTYPE;
  target_class text;
BEGIN
  SELECT * INTO assessment FROM domain_compatibility_assessments WHERE assessment_id = NEW.compatibility_assessment_id;
  SELECT * INTO event_row FROM telemetry_events WHERE event_id = NEW.telemetry_event_id;
  SELECT equipment_class_id INTO target_class FROM assets WHERE asset_id = NEW.target_asset_id;

  IF assessment.subject_type <> 'EVENT_CLASS' OR assessment.subject_id <> event_row.source_event_class
     OR assessment.source_system_id <> event_row.source_system_id THEN
    RAISE EXCEPTION 'assessment % does not cover event class %', assessment.assessment_id, event_row.source_event_class
      USING ERRCODE = 'check_violation';
  END IF;
  IF target_class IS DISTINCT FROM assessment.target_equipment_class_id THEN
    RAISE EXCEPTION 'assessment % does not cover target class %', assessment.assessment_id, target_class
      USING ERRCODE = 'check_violation';
  END IF;
  IF assessment.classification IN ('INCOMPATIBLE', 'INSUFFICIENT_EVIDENCE') THEN
    RAISE EXCEPTION 'event class % is % for %', event_row.source_event_class, assessment.classification, target_class
      USING ERRCODE = 'check_violation';
  END IF;
  IF assessment.classification = 'CONDITIONALLY_COMPATIBLE'
     AND (NEW.conditions_satisfied IS NULL OR jsonb_array_length(NEW.conditions_satisfied) < jsonb_array_length(assessment.conditions)) THEN
    RAISE EXCEPTION 'conditional assessment % needs evidence for every condition', assessment.assessment_id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER scenario_mapping_guard BEFORE INSERT ON scenario_mappings
  FOR EACH ROW EXECUTE FUNCTION enforce_scenario_mapping();

CREATE FUNCTION reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is immutable; % rejected', TG_TABLE_NAME, TG_OP USING ERRCODE = 'restrict_violation';
END $$;
CREATE TRIGGER scenario_mapping_immutable BEFORE UPDATE OR DELETE ON scenario_mappings
  FOR EACH ROW EXECUTE FUNCTION reject_change();

CREATE TABLE asset_observation_links (
  link_id            bigserial PRIMARY KEY,
  source_asset_id    text REFERENCES source_assets,
  asset_id           text REFERENCES assets,
  observation_id     bigint NOT NULL REFERENCES observations,
  relationship_type  text NOT NULL CHECK (relationship_type IN (
    'MEASURED_AT', 'IMAGE_COVERS', 'EMISSION_NEAR', 'SOURCE_ATTRIBUTED_TO', 'ASSOCIATED_WITH', 'EXPERIMENTAL_SCENARIO_LINK'
  )),
  evidence_reference text,
  confidence         double precision CHECK (confidence BETWEEN 0 AND 1),
  verification_status verification_status NOT NULL,
  method_version     text NOT NULL,
  provenance_class   provenance_class NOT NULL,
  scenario_id        text REFERENCES scenarios,
  CONSTRAINT link_has_one_target CHECK (num_nonnulls(source_asset_id, asset_id) = 1),
  -- A fictional asset can only ever hold an explicit experimental link.
  CONSTRAINT fictional_links_are_experimental CHECK (
    asset_id IS NULL OR (
      relationship_type = 'EXPERIMENTAL_SCENARIO_LINK' AND scenario_id IS NOT NULL
      AND provenance_class IN ('REPLAYED', 'SYNTHETIC', 'INFERRED') AND verification_status <> 'VERIFIED'
    )
  ),
  CONSTRAINT real_links_are_not_experimental CHECK (source_asset_id IS NULL OR relationship_type <> 'EXPERIMENTAL_SCENARIO_LINK'),
  -- No evidence, no confidence value.
  CONSTRAINT confidence_needs_evidence CHECK (confidence IS NULL OR evidence_reference IS NOT NULL),
  CONSTRAINT attribution_needs_verified_evidence CHECK (
    relationship_type <> 'SOURCE_ATTRIBUTED_TO' OR (verification_status = 'VERIFIED' AND evidence_reference IS NOT NULL)
  ),
  CONSTRAINT proximity_is_not_verified_attribution CHECK (relationship_type <> 'EMISSION_NEAR' OR verification_status <> 'VERIFIED')
);
COMMENT ON TABLE asset_observation_links IS 'Links from observations to either a real or a fictional asset, never both.';
CREATE UNIQUE INDEX link_real_unique ON asset_observation_links (source_asset_id, observation_id, relationship_type) WHERE source_asset_id IS NOT NULL;
CREATE UNIQUE INDEX link_fictional_unique ON asset_observation_links (asset_id, observation_id, scenario_id) WHERE asset_id IS NOT NULL;

CREATE FUNCTION enforce_observation_link() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  observation_system text;
  asset_system text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.relationship_type <> OLD.relationship_type THEN
    RAISE EXCEPTION 'relationship_type is immutable. Add a new reviewed link instead of promoting %', OLD.relationship_type
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.relationship_type = 'MEASURED_AT' THEN
    SELECT source_system_id INTO observation_system FROM observations WHERE observation_id = NEW.observation_id;
    SELECT source_system_id INTO asset_system FROM source_assets WHERE source_asset_id = NEW.source_asset_id;
    IF observation_system IS DISTINCT FROM asset_system THEN
      RAISE EXCEPTION 'MEASURED_AT requires one source system: observation is %, asset is %', observation_system, asset_system
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER observation_link_guard BEFORE INSERT OR UPDATE ON asset_observation_links
  FOR EACH ROW EXECUTE FUNCTION enforce_observation_link();
