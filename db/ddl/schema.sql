--
-- PostgreSQL database dump
--

-- Dumped from database version 16.4 (Debian 16.4-1.pgdg110+2)
-- Dumped by pg_dump version 16.4 (Debian 16.4-1.pgdg110+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: tiger; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA tiger;


--
-- Name: tiger_data; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA tiger_data;


--
-- Name: topology; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA topology;


--
-- Name: SCHEMA topology; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA topology IS 'PostGIS Topology schema';


--
-- Name: btree_gist; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;


--
-- Name: EXTENSION btree_gist; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION btree_gist IS 'support for indexing common datatypes in GiST';


--
-- Name: fuzzystrmatch; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS fuzzystrmatch WITH SCHEMA public;


--
-- Name: EXTENSION fuzzystrmatch; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION fuzzystrmatch IS 'determine similarities and distance between strings';


--
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry and geography spatial types and functions';


--
-- Name: postgis_tiger_geocoder; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder WITH SCHEMA tiger;


--
-- Name: EXTENSION postgis_tiger_geocoder; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis_tiger_geocoder IS 'PostGIS tiger geocoder and reverse geocoder';


--
-- Name: postgis_topology; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis_topology WITH SCHEMA topology;


--
-- Name: EXTENSION postgis_topology; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis_topology IS 'PostGIS topology spatial types and functions';


--
-- Name: compatibility_class; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.compatibility_class AS ENUM (
    'DIRECTLY_COMPATIBLE',
    'CONDITIONALLY_COMPATIBLE',
    'INCOMPATIBLE',
    'INSUFFICIENT_EVIDENCE'
);


--
-- Name: instance_origin; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.instance_origin AS ENUM (
    'REAL',
    'SIMULATED',
    'HAND_DRAWN'
);


--
-- Name: provenance_class; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.provenance_class AS ENUM (
    'OBSERVED',
    'DERIVED',
    'REPLAYED',
    'SYNTHETIC',
    'INFERRED'
);


--
-- Name: reference_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.reference_type AS ENUM (
    'ABSOLUTE',
    'GAUGE',
    'DIFFERENTIAL',
    'UNKNOWN',
    'NOT_APPLICABLE'
);


--
-- Name: spatial_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.spatial_status AS ENUM (
    'USABLE',
    'QUARANTINED',
    'UNRESOLVED_DATUM',
    'NO_LOCATION'
);


--
-- Name: verification_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.verification_status AS ENUM (
    'VERIFIED',
    'UNVERIFIED',
    'UNRESOLVED',
    'REJECTED'
);


--
-- Name: enforce_benchmark_event_origin(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_benchmark_event_origin() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_domain_boundary(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_domain_boundary() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_equipment_relationship(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_equipment_relationship() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_fictional_link_chain(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_fictional_link_chain() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_observation_link(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_observation_link() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_observation_sensor_source(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_observation_sensor_source() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_physical_connection(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_physical_connection() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_recommendation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_recommendation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_request_trigger(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_request_trigger() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_review_chain(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_review_chain() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  observation_system text;
  observation_record text;
  previous_evidence text;
BEGIN
  SELECT source_system_id, source_record_id INTO observation_system, observation_record
    FROM observations WHERE observation_id = NEW.observation_id;
  -- The kind, the identifier, and the observation must all name the same piece of evidence.
  IF NOT ((NEW.evidence_kind = 'PLUME' AND observation_system = 'carbon_mapper')
       OR (NEW.evidence_kind = 'NAIP_CHIP' AND observation_system = 'naip')) THEN
    RAISE EXCEPTION 'evidence kind % does not match an observation from %', NEW.evidence_kind, observation_system
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.evidence_id IS DISTINCT FROM observation_record THEN
    RAISE EXCEPTION 'evidence_id % is not the identifier of observation % (%)',
      NEW.evidence_id, NEW.observation_id, observation_record USING ERRCODE = 'check_violation';
  END IF;
  IF cardinality(NEW.visible_features) <> (SELECT count(DISTINCT f) FROM unnest(NEW.visible_features) AS f) THEN
    RAISE EXCEPTION 'each visible feature is recorded once' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.supersedes IS NOT NULL THEN
    SELECT evidence_id INTO previous_evidence FROM inspection_review_events WHERE review_id = NEW.supersedes;
    IF previous_evidence IS DISTINCT FROM NEW.evidence_id THEN
      RAISE EXCEPTION 'a review can only supersede a review of the same evidence' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;


--
-- Name: enforce_scenario_mapping(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_scenario_mapping() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_status_change(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_status_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_transition_order(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_transition_order() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: enforce_work_order_creation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_work_order_creation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: reject_change(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.reject_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION '% is immutable; % rejected', TG_TABLE_NAME, TG_OP USING ERRCODE = 'restrict_violation';
END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: anomaly_predictions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.anomaly_predictions (
    prediction_id bigint NOT NULL,
    scenario_id text,
    source_event_id text NOT NULL,
    model_version text NOT NULL,
    event_timestamp timestamp without time zone NOT NULL,
    predicted_class text NOT NULL,
    anomaly_score double precision,
    decision_threshold double precision,
    evidence_reference text NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    CONSTRAINT anomaly_predictions_provenance_class_check CHECK ((provenance_class = ANY (ARRAY['DERIVED'::public.provenance_class, 'INFERRED'::public.provenance_class, 'SYNTHETIC'::public.provenance_class])))
);


--
-- Name: anomaly_predictions_prediction_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.anomaly_predictions_prediction_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: anomaly_predictions_prediction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.anomaly_predictions_prediction_id_seq OWNED BY public.anomaly_predictions.prediction_id;


--
-- Name: approval_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_events (
    approval_id bigint NOT NULL,
    work_order_id bigint NOT NULL,
    actor_id text NOT NULL,
    action text NOT NULL,
    justification text NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    actor_kind text,
    actor_role text,
    CONSTRAINT approval_events_action_check CHECK ((action = ANY (ARRAY['APPROVE'::text, 'REJECT'::text, 'REQUEST_EVIDENCE'::text]))),
    CONSTRAINT approval_events_actor_kind_check CHECK ((actor_kind = ANY (ARRAY['HUMAN'::text, 'SCRIPTED_DEMO'::text])))
);


--
-- Name: approval_events_approval_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_events_approval_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_events_approval_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_events_approval_id_seq OWNED BY public.approval_events.approval_id;


--
-- Name: asset_observation_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset_observation_links (
    link_id bigint NOT NULL,
    source_asset_id text,
    asset_id text,
    observation_id bigint NOT NULL,
    relationship_type text NOT NULL,
    evidence_reference text,
    confidence double precision,
    verification_status public.verification_status NOT NULL,
    method_version text NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    scenario_id text,
    CONSTRAINT asset_observation_links_confidence_check CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT asset_observation_links_relationship_type_check CHECK ((relationship_type = ANY (ARRAY['MEASURED_AT'::text, 'IMAGE_COVERS'::text, 'EMISSION_NEAR'::text, 'SOURCE_ATTRIBUTED_TO'::text, 'ASSOCIATED_WITH'::text, 'EXPERIMENTAL_SCENARIO_LINK'::text]))),
    CONSTRAINT attribution_needs_verified_evidence CHECK (((relationship_type <> 'SOURCE_ATTRIBUTED_TO'::text) OR ((verification_status = 'VERIFIED'::public.verification_status) AND (evidence_reference IS NOT NULL)))),
    CONSTRAINT confidence_needs_evidence CHECK (((confidence IS NULL) OR (evidence_reference IS NOT NULL))),
    CONSTRAINT fictional_links_are_experimental CHECK (((asset_id IS NULL) OR ((relationship_type = 'EXPERIMENTAL_SCENARIO_LINK'::text) AND (scenario_id IS NOT NULL) AND (provenance_class = ANY (ARRAY['REPLAYED'::public.provenance_class, 'SYNTHETIC'::public.provenance_class, 'INFERRED'::public.provenance_class])) AND (verification_status <> 'VERIFIED'::public.verification_status)))),
    CONSTRAINT link_has_one_target CHECK ((num_nonnulls(source_asset_id, asset_id) = 1)),
    CONSTRAINT proximity_is_not_verified_attribution CHECK (((relationship_type <> 'EMISSION_NEAR'::text) OR (verification_status <> 'VERIFIED'::public.verification_status))),
    CONSTRAINT real_links_are_not_experimental CHECK (((source_asset_id IS NULL) OR (relationship_type <> 'EXPERIMENTAL_SCENARIO_LINK'::text)))
);


--
-- Name: TABLE asset_observation_links; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.asset_observation_links IS 'Links from observations to either a real or a fictional asset, never both.';


--
-- Name: asset_observation_links_link_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.asset_observation_links_link_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: asset_observation_links_link_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.asset_observation_links_link_id_seq OWNED BY public.asset_observation_links.link_id;


--
-- Name: asset_relationships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset_relationships (
    relationship_id bigint NOT NULL,
    source_asset_id text NOT NULL,
    target_asset_id text NOT NULL,
    relationship_type text NOT NULL,
    evidence_type text NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    effective_from date DEFAULT '-infinity'::date NOT NULL,
    effective_to date,
    CONSTRAINT asset_relationships_provenance_class_check CHECK ((provenance_class = ANY (ARRAY['SYNTHETIC'::public.provenance_class, 'INFERRED'::public.provenance_class]))),
    CONSTRAINT relationship_not_self CHECK ((source_asset_id <> target_asset_id)),
    CONSTRAINT relationship_validity CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: TABLE asset_relationships; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.asset_relationships IS 'Relationships between fictional assets. They can never be OBSERVED.';


--
-- Name: asset_relationships_relationship_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.asset_relationships_relationship_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: asset_relationships_relationship_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.asset_relationships_relationship_id_seq OWNED BY public.asset_relationships.relationship_id;


--
-- Name: assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.assets (
    asset_id text NOT NULL,
    facility_id text NOT NULL,
    parent_asset_id text,
    asset_type text NOT NULL,
    asset_name text NOT NULL,
    equipment_class_id text,
    operating_status text,
    geometry public.geometry(Point,4326),
    is_fictional boolean NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    transformation_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT assets_is_fictional_check CHECK (is_fictional),
    CONSTRAINT assets_provenance_class_check CHECK ((provenance_class = 'SYNTHETIC'::public.provenance_class))
);


--
-- Name: TABLE assets; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.assets IS 'Facility assets. Currently fictional only and always SYNTHETIC. Geometry is added in Gate 4.';


--
-- Name: audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events (
    event_id bigint NOT NULL,
    actor_id text NOT NULL,
    operation text NOT NULL,
    target_id text NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    correlation_id text NOT NULL,
    before_state_reference text,
    after_state_reference text
);


--
-- Name: audit_events_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_events_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_events_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_events_event_id_seq OWNED BY public.audit_events.event_id;


--
-- Name: batch_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.batch_files (
    batch_id text NOT NULL,
    path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes bigint NOT NULL,
    source_url text NOT NULL,
    source_modified text,
    upstream_checksum text,
    CONSTRAINT batch_files_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT batch_files_size_bytes_check CHECK ((size_bytes >= 0))
);


--
-- Name: TABLE batch_files; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.batch_files IS 'Raw files behind a batch, so a canonical row can be traced to bytes on disk.';


--
-- Name: data_quality_exceptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_quality_exceptions (
    exception_id bigint NOT NULL,
    exception_type text NOT NULL,
    severity text NOT NULL,
    source_system_id text NOT NULL,
    batch_id text NOT NULL,
    dataset text NOT NULL,
    source_asset_id text,
    source_record_key text NOT NULL,
    field_name text,
    original_values jsonb NOT NULL,
    evidence jsonb NOT NULL,
    rule_id text NOT NULL,
    disposition text NOT NULL,
    status text NOT NULL,
    decision_rationale text NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_quality_exceptions_disposition_check CHECK ((disposition = ANY (ARRAY['QUARANTINED_FROM_SPATIAL'::text, 'QUARANTINED_RECORD'::text, 'FLAGGED_UNRESOLVED'::text, 'ACCEPTED_WITH_NOTE'::text]))),
    CONSTRAINT data_quality_exceptions_severity_check CHECK ((severity = ANY (ARRAY['ERROR'::text, 'WARNING'::text, 'INFO'::text]))),
    CONSTRAINT data_quality_exceptions_status_check CHECK ((status = ANY (ARRAY['OPEN'::text, 'ACCEPTED'::text, 'RESOLVED'::text])))
);


--
-- Name: TABLE data_quality_exceptions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.data_quality_exceptions IS 'Every known defect, with the original value, evidence, and decision. Exceptions never alter source values.';


--
-- Name: data_quality_exceptions_exception_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_quality_exceptions_exception_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_quality_exceptions_exception_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_quality_exceptions_exception_id_seq OWNED BY public.data_quality_exceptions.exception_id;


--
-- Name: detector_alarms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.detector_alarms (
    alarm_id text NOT NULL,
    scenario_id text NOT NULL,
    scenario_run_id text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    score double precision NOT NULL,
    threshold double precision NOT NULL,
    model_id text NOT NULL,
    model_version text NOT NULL,
    model_sha256 text NOT NULL,
    evidence jsonb NOT NULL,
    earlier_starts_in_lookback integer NOT NULL,
    first_alarm_at timestamp with time zone NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    input_provenance public.provenance_class NOT NULL,
    CONSTRAINT alarm_crossed_threshold CHECK ((score >= threshold)),
    CONSTRAINT detector_alarms_check CHECK ((first_alarm_at <= started_at)),
    CONSTRAINT detector_alarms_earlier_starts_in_lookback_check CHECK ((earlier_starts_in_lookback >= 0)),
    CONSTRAINT detector_alarms_evidence_check CHECK ((jsonb_typeof(evidence) = 'array'::text)),
    CONSTRAINT detector_alarms_input_provenance_check CHECK ((input_provenance = 'SYNTHETIC'::public.provenance_class)),
    CONSTRAINT detector_alarms_model_sha256_check CHECK ((model_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT detector_alarms_provenance_class_check CHECK ((provenance_class = 'INFERRED'::public.provenance_class))
);


--
-- Name: TABLE detector_alarms; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.detector_alarms IS 'Alarm starts from the Gate 5 detector on simulated telemetry. A score is never a failure probability.';


--
-- Name: domain_boundaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.domain_boundaries (
    source_system_id text NOT NULL,
    target_domain text NOT NULL,
    is_allowed boolean NOT NULL,
    rationale text NOT NULL,
    CONSTRAINT domain_boundaries_target_domain_check CHECK ((target_domain = ANY (ARRAY['REAL_ONSHORE'::text, 'REAL_OFFSHORE'::text, 'FICTIONAL_ONSHORE'::text])))
);


--
-- Name: TABLE domain_boundaries; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.domain_boundaries IS 'Whether a source may be mapped onto a target domain. A missing row means refused.';


--
-- Name: domain_compatibility_assessments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.domain_compatibility_assessments (
    assessment_id text NOT NULL,
    source_system_id text NOT NULL,
    subject_type text NOT NULL,
    subject_id text NOT NULL,
    target_equipment_class_id text NOT NULL,
    classification public.compatibility_class NOT NULL,
    reasoning text NOT NULL,
    conditions jsonb DEFAULT '[]'::jsonb NOT NULL,
    assessment_version integer NOT NULL,
    assessed_on date NOT NULL,
    CONSTRAINT conditional_states_conditions CHECK (((classification <> 'CONDITIONALLY_COMPATIBLE'::public.compatibility_class) OR (jsonb_array_length(conditions) > 0))),
    CONSTRAINT domain_compatibility_assessments_subject_type_check CHECK ((subject_type = ANY (ARRAY['VARIABLE'::text, 'EVENT_CLASS'::text])))
);


--
-- Name: TABLE domain_compatibility_assessments; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.domain_compatibility_assessments IS 'Engineering judgment, versioned. Not field validation. Generated from data_contracts/semantic_mappings/3w_aether_compatibility.yaml.';


--
-- Name: domain_compatibility_requirements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.domain_compatibility_requirements (
    requirement_id text NOT NULL,
    target_equipment_class_id text NOT NULL,
    category text NOT NULL,
    requirement text NOT NULL,
    target_value text NOT NULL,
    rationale text NOT NULL
);


--
-- Name: TABLE domain_compatibility_requirements; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.domain_compatibility_requirements IS 'Equipment and operating conditions that telemetry must meet before it can be applied to an experimental asset.';


--
-- Name: equipment_classes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.equipment_classes (
    equipment_class_id text NOT NULL,
    name text NOT NULL,
    domain text NOT NULL,
    description text NOT NULL,
    basis text NOT NULL,
    CONSTRAINT equipment_classes_domain_check CHECK ((domain = ANY (ARRAY['REAL_ONSHORE'::text, 'REAL_OFFSHORE'::text, 'FICTIONAL_ONSHORE'::text])))
);


--
-- Name: TABLE equipment_classes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.equipment_classes IS 'Physical classes of equipment. Measurement semantics belong to a class, which is what keeps offshore and onshore measurements apart.';


--
-- Name: equipment_measurement_capabilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.equipment_measurement_capabilities (
    equipment_class_id text NOT NULL,
    measurement_definition_id text NOT NULL,
    capability text NOT NULL,
    basis text NOT NULL,
    CONSTRAINT equipment_measurement_capabilities_capability_check CHECK ((capability = ANY (ARRAY['EXPECTED'::text, 'OPTIONAL'::text, 'SOURCE_REPORTED'::text])))
);


--
-- Name: TABLE equipment_measurement_capabilities; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.equipment_measurement_capabilities IS 'Which measurements a class can provide. SOURCE_REPORTED means the source publishes it; the others are AETHER design assumptions.';


--
-- Name: equipment_relationship_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.equipment_relationship_rules (
    source_asset_type text NOT NULL,
    relationship_type text NOT NULL,
    target_asset_type text NOT NULL,
    rationale text NOT NULL
);


--
-- Name: TABLE equipment_relationship_rules; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.equipment_relationship_rules IS 'The fictional facility''s allowed flow connections. Anything not listed is refused.';


--
-- Name: facilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.facilities (
    facility_id text NOT NULL,
    facility_name text NOT NULL,
    facility_type text NOT NULL,
    region text NOT NULL,
    is_fictional boolean NOT NULL,
    disclosure text NOT NULL,
    geometry public.geometry(Geometry,4326),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT aether_is_fictional CHECK (((facility_id <> 'AETHER-FIELD'::text) OR is_fictional))
);


--
-- Name: ingestion_batches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingestion_batches (
    batch_id text NOT NULL,
    source_system_id text NOT NULL,
    source_version text NOT NULL,
    ingestion_timestamp timestamp with time zone NOT NULL,
    original_checksum text NOT NULL,
    source_record_count integer NOT NULL,
    accepted_count integer NOT NULL,
    rejected_count integer NOT NULL,
    processing_status text NOT NULL,
    manifest_uri text NOT NULL,
    notes jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT batch_counts_reconcile CHECK (((accepted_count + rejected_count) = source_record_count)),
    CONSTRAINT ingestion_batches_accepted_count_check CHECK ((accepted_count >= 0)),
    CONSTRAINT ingestion_batches_original_checksum_check CHECK ((original_checksum ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT ingestion_batches_processing_status_check CHECK ((processing_status = ANY (ARRAY['COMPLETE'::text, 'FAILED'::text]))),
    CONSTRAINT ingestion_batches_rejected_count_check CHECK ((rejected_count >= 0)),
    CONSTRAINT ingestion_batches_source_record_count_check CHECK ((source_record_count >= 0))
);


--
-- Name: TABLE ingestion_batches; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.ingestion_batches IS 'One row per acquisition manifest. Accepted plus rejected must equal the source count.';


--
-- Name: inspection_observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inspection_observations (
    inspection_id bigint NOT NULL,
    observation_id bigint NOT NULL,
    inspection_type text NOT NULL,
    source_asset_candidate_id text,
    asset_candidate_id text,
    evidence_uri text NOT NULL,
    finding text,
    reviewer text,
    confidence double precision,
    review_status text NOT NULL,
    CONSTRAINT candidate_is_real_or_fictional CHECK ((num_nonnulls(source_asset_candidate_id, asset_candidate_id) <= 1)),
    CONSTRAINT inspection_observations_confidence_check CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT inspection_observations_review_status_check CHECK ((review_status = ANY (ARRAY['PENDING'::text, 'REVIEWED'::text, 'REJECTED'::text]))),
    CONSTRAINT reviewed_has_reviewer CHECK (((review_status = 'PENDING'::text) OR (reviewer IS NOT NULL)))
);


--
-- Name: inspection_observations_inspection_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.inspection_observations_inspection_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: inspection_observations_inspection_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.inspection_observations_inspection_id_seq OWNED BY public.inspection_observations.inspection_id;


--
-- Name: inspection_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inspection_requests (
    request_id text NOT NULL,
    asset_id text NOT NULL,
    affected_asset_id text NOT NULL,
    scenario_id text NOT NULL,
    scenario_run_id text NOT NULL,
    trigger_event_id text NOT NULL,
    inspection_type text NOT NULL,
    reason text NOT NULL,
    status text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    CONSTRAINT inspection_requests_inspection_type_check CHECK ((inspection_type = ANY (ARRAY['GROUND_INSPECTION'::text, 'AERIAL_SURVEY'::text]))),
    CONSTRAINT inspection_requests_provenance_class_check CHECK ((provenance_class = 'SYNTHETIC'::public.provenance_class)),
    CONSTRAINT inspection_requests_status_check CHECK ((status = ANY (ARRAY['REQUESTED'::text, 'CANCELLED'::text, 'COMPLETED'::text])))
);


--
-- Name: TABLE inspection_requests; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.inspection_requests IS 'Simulated inspection requests on fictional assets. No priority score; Gate 7 owns prioritization.';


--
-- Name: inspection_review_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inspection_review_events (
    review_id text NOT NULL,
    evidence_id text NOT NULL,
    evidence_kind text NOT NULL,
    observation_id bigint NOT NULL,
    reviewer text NOT NULL,
    outcome text NOT NULL,
    visible_features text[] DEFAULT '{}'::text[] NOT NULL,
    blinded_to_plume_status boolean NOT NULL,
    supersedes text,
    recorded_at timestamp with time zone NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    CONSTRAINT inspection_review_events_blinded_to_plume_status_check CHECK (blinded_to_plume_status),
    CONSTRAINT inspection_review_events_evidence_kind_check CHECK ((evidence_kind = ANY (ARRAY['NAIP_CHIP'::text, 'PLUME'::text]))),
    CONSTRAINT inspection_review_events_outcome_check CHECK ((outcome = ANY (ARRAY['NO_FEATURE_OF_NOTE'::text, 'INFRASTRUCTURE_VISIBLE'::text, 'IMAGE_UNUSABLE'::text, 'FIELD_VERIFICATION_SUGGESTED'::text]))),
    CONSTRAINT inspection_review_events_provenance_class_check CHECK ((provenance_class = 'OBSERVED'::public.provenance_class)),
    CONSTRAINT inspection_review_events_reviewer_check CHECK ((length(btrim(reviewer)) > 0)),
    CONSTRAINT inspection_review_events_visible_features_check CHECK ((visible_features <@ ARRAY['WELL_PAD'::text, 'WELLHEAD_EQUIPMENT'::text, 'TANK_BATTERY'::text, 'COMPRESSION_EQUIPMENT'::text, 'FLARE_STACK'::text, 'PIT_OR_POND'::text, 'PIPELINE_CORRIDOR'::text, 'OTHER_STRUCTURE'::text, 'CLOUD_OR_SHADOW'::text, 'IMAGE_ARTIFACT'::text]))
);


--
-- Name: TABLE inspection_review_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.inspection_review_events IS 'Reviewer findings on real aerial evidence. No outcome confirms a leak or names a source.';


--
-- Name: measurement_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.measurement_definitions (
    measurement_definition_id text NOT NULL,
    equipment_class_id text NOT NULL,
    physical_quantity text NOT NULL,
    equipment_location text NOT NULL,
    reference_type public.reference_type NOT NULL,
    canonical_unit_id text NOT NULL,
    description text NOT NULL,
    CONSTRAINT definition_reference_fits_quantity CHECK ((((physical_quantity = 'pressure'::text) AND (reference_type <> 'NOT_APPLICABLE'::public.reference_type)) OR ((physical_quantity <> 'pressure'::text) AND (reference_type = 'NOT_APPLICABLE'::public.reference_type))))
);


--
-- Name: TABLE measurement_definitions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.measurement_definitions IS 'A measurement belongs to one equipment class. There is no shared generic pressure definition.';


--
-- Name: observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.observations (
    observation_id bigint NOT NULL,
    source_system_id text NOT NULL,
    source_record_id text NOT NULL,
    observed_at timestamp without time zone,
    observation_type text NOT NULL,
    metric_name text NOT NULL,
    numeric_value double precision,
    unit_id text,
    quality_flag text NOT NULL,
    geometry public.geometry(Geometry,4326),
    provenance_class public.provenance_class NOT NULL,
    original_record_uri text NOT NULL,
    sensor_tag_id text,
    telemetry_event_id text,
    value_count integer,
    null_count integer,
    replayed_from_observation_id bigint,
    scenario_id text,
    batch_id text,
    transformation_id text NOT NULL,
    scenario_run_id text,
    CONSTRAINT observations_null_count_check CHECK ((null_count >= 0)),
    CONSTRAINT observations_observation_type_check CHECK ((observation_type = ANY (ARRAY['TELEMETRY_SERIES'::text, 'POINT_VALUE'::text, 'REMOTE_SENSING'::text, 'IMAGE'::text]))),
    CONSTRAINT observations_value_count_check CHECK ((value_count >= 0)),
    CONSTRAINT observed_has_batch CHECK (((provenance_class <> 'OBSERVED'::public.provenance_class) OR (batch_id IS NOT NULL))),
    CONSTRAINT replay_keeps_origin CHECK ((((provenance_class = 'REPLAYED'::public.provenance_class) = (replayed_from_observation_id IS NOT NULL)) AND ((provenance_class <> 'REPLAYED'::public.provenance_class) OR (scenario_id IS NOT NULL)))),
    CONSTRAINT simulated_series_is_synthetic CHECK (((scenario_run_id IS NULL) OR ((provenance_class = 'SYNTHETIC'::public.provenance_class) AND (scenario_id IS NOT NULL)))),
    CONSTRAINT synthetic_source_requires_run CHECK (((source_system_id = 'aether_synthetic'::text) = (scenario_run_id IS NOT NULL))),
    CONSTRAINT synthetic_source_requires_sensor CHECK (((source_system_id <> 'aether_synthetic'::text) OR (sensor_tag_id IS NOT NULL)))
);


--
-- Name: TABLE observations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.observations IS 'Queryable metadata. High-volume sensor values stay in Parquet; one TELEMETRY_SERIES row describes each sensor in each instance.';


--
-- Name: COLUMN observations.observed_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.observations.observed_at IS 'As reported, with no time zone assumed.';


--
-- Name: observations_observation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.observations_observation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: observations_observation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.observations_observation_id_seq OWNED BY public.observations.observation_id;


--
-- Name: physical_connection_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.physical_connection_rules (
    edge_type text NOT NULL,
    from_node_type text NOT NULL,
    to_node_type text NOT NULL
);


--
-- Name: TABLE physical_connection_rules; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.physical_connection_rules IS 'Allowed physical connections. Anything not listed is refused.';


--
-- Name: physical_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.physical_edges (
    edge_id text NOT NULL,
    edge_type text NOT NULL,
    from_node_id text NOT NULL,
    to_node_id text NOT NULL,
    element_asset_id text NOT NULL,
    valve_asset_id text,
    length_m double precision,
    diameter_m double precision,
    network_version integer NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    CONSTRAINT edge_not_self CHECK ((from_node_id <> to_node_id)),
    CONSTRAINT physical_edges_diameter_m_check CHECK ((diameter_m > (0)::double precision)),
    CONSTRAINT physical_edges_edge_type_check CHECK ((edge_type = ANY (ARRAY['WELL_INFLOW'::text, 'FLOWLINE'::text, 'GATHERING_SEGMENT'::text, 'COMPRESSION'::text, 'ACCESS_ROUTE'::text]))),
    CONSTRAINT physical_edges_length_m_check CHECK ((length_m > (0)::double precision)),
    CONSTRAINT physical_edges_network_version_check CHECK ((network_version > 0)),
    CONSTRAINT physical_edges_provenance_class_check CHECK ((provenance_class = 'SYNTHETIC'::public.provenance_class)),
    CONSTRAINT pipes_have_geometry CHECK (((edge_type <> ALL (ARRAY['FLOWLINE'::text, 'GATHERING_SEGMENT'::text])) OR ((length_m IS NOT NULL) AND (diameter_m IS NOT NULL))))
);


--
-- Name: TABLE physical_edges; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.physical_edges IS 'Directed connections. A closed valve or stopped machine is a run state, so this graph stays fixed.';


--
-- Name: physical_nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.physical_nodes (
    node_id text NOT NULL,
    facility_id text NOT NULL,
    node_type text NOT NULL,
    asset_id text NOT NULL,
    local_x_m double precision,
    local_y_m double precision,
    network_version integer NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    CONSTRAINT coordinates_together CHECK (((local_x_m IS NULL) = (local_y_m IS NULL))),
    CONSTRAINT physical_nodes_network_version_check CHECK ((network_version > 0)),
    CONSTRAINT physical_nodes_node_type_check CHECK ((node_type = ANY (ARRAY['RESERVOIR_BOUNDARY'::text, 'WELLHEAD'::text, 'JUNCTION'::text, 'MANIFOLD'::text, 'SUCTION_HEADER'::text, 'DISCHARGE_BOUNDARY'::text, 'SITE'::text]))),
    CONSTRAINT physical_nodes_provenance_class_check CHECK ((provenance_class = 'SYNTHETIC'::public.provenance_class))
);


--
-- Name: TABLE physical_nodes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.physical_nodes IS 'Places where pressure is defined, or fictional sites. Local metres from a fictional origin, so no real location is implied.';


--
-- Name: production_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.production_records (
    record_id bigint NOT NULL,
    source_system_id text NOT NULL,
    reporting_entity_id text NOT NULL,
    reporting_grain text NOT NULL,
    reporting_period date NOT NULL,
    product_kind text NOT NULL,
    reported_volume bigint,
    unit_id text NOT NULL,
    unit_system text NOT NULL,
    pool_code text NOT NULL,
    operator_code text NOT NULL,
    days_produced smallint,
    completion_status_code text,
    is_amended boolean,
    source_effective_at timestamp without time zone NOT NULL,
    source_modified_at timestamp without time zone,
    original_record_uri text NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    batch_id text NOT NULL,
    transformation_id text NOT NULL,
    source_record_key text NOT NULL,
    CONSTRAINT production_records_days_produced_check CHECK (((days_produced >= 0) AND (days_produced <= 31))),
    CONSTRAINT production_records_provenance_class_check CHECK ((provenance_class = 'OBSERVED'::public.provenance_class)),
    CONSTRAINT production_records_reported_volume_check CHECK ((reported_volume >= 0)),
    CONSTRAINT production_records_reporting_grain_check CHECK ((reporting_grain = ANY (ARRAY['WELL_COMPLETION'::text, 'WELL'::text, 'LEASE'::text, 'OPERATOR'::text]))),
    CONSTRAINT production_records_reporting_period_check CHECK ((EXTRACT(day FROM reporting_period) = (1)::numeric))
);


--
-- Name: TABLE production_records; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.production_records IS 'One row per source row: completion, month, and product. Volumes are unaltered. v_production_wide gives the oil, gas, and water columns.';


--
-- Name: COLUMN production_records.reporting_period; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.production_records.reporting_period IS 'First day of the month the fluid was produced. This is the production date.';


--
-- Name: COLUMN production_records.is_amended; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.production_records.is_amended IS 'OCD amend_ind. The current value replaced an earlier report, and the earlier value is not in the extract.';


--
-- Name: COLUMN production_records.source_effective_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.production_records.source_effective_at IS 'OCD eff_dte as reported, with no time zone stated. Not the production date. Filing-like in recent rows, but OCD does not define it as a filing date.';


--
-- Name: production_records_record_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.production_records_record_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: production_records_record_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.production_records_record_id_seq OWNED BY public.production_records.record_id;


--
-- Name: production_unit_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.production_unit_rules (
    source_system_id text NOT NULL,
    product_kind text NOT NULL,
    unit_id text NOT NULL,
    product_scope text NOT NULL,
    base_conditions text NOT NULL,
    verification_status public.verification_status NOT NULL,
    evidence jsonb NOT NULL,
    CONSTRAINT unit_rule_has_evidence CHECK ((jsonb_array_length(evidence) > 0))
);


--
-- Name: TABLE production_unit_rules; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.production_unit_rules IS 'Verified meaning of each product kind. A production row must match a rule, so ambiguous units cannot be stored.';


--
-- Name: recommendations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recommendations (
    recommendation_id text NOT NULL,
    alarm_id text NOT NULL,
    scenario_id text NOT NULL,
    scenario_run_id text NOT NULL,
    decided_at timestamp with time zone NOT NULL,
    action text NOT NULL,
    candidate_assets text[] NOT NULL,
    suppressed_assets text[] NOT NULL,
    priority_score integer NOT NULL,
    priority_band text,
    respond_within_h integer,
    terms jsonb NOT NULL,
    explanation jsonb NOT NULL,
    rules_version integer NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    CONSTRAINT dispatch_has_band_and_candidate CHECK (((action = ANY (ARRAY['FIELD_INSPECTION'::text, 'CHECK_INSTRUMENTATION'::text])) = ((priority_band IS NOT NULL) AND (cardinality(candidate_assets) > 0)))),
    CONSTRAINT recommendations_action_check CHECK ((action = ANY (ARRAY['FIELD_INSPECTION'::text, 'CHECK_INSTRUMENTATION'::text, 'NO_ACTION_PLANNED_OPERATION'::text, 'NEEDS_EVIDENCE'::text]))),
    CONSTRAINT recommendations_explanation_check CHECK (((jsonb_typeof(explanation) = 'array'::text) AND (jsonb_array_length(explanation) > 0))),
    CONSTRAINT recommendations_priority_band_check CHECK ((priority_band = ANY (ARRAY['P1'::text, 'P2'::text, 'P3'::text]))),
    CONSTRAINT recommendations_priority_score_check CHECK ((priority_score >= 0)),
    CONSTRAINT recommendations_provenance_class_check CHECK ((provenance_class = 'SYNTHETIC'::public.provenance_class)),
    CONSTRAINT recommendations_respond_within_h_check CHECK ((respond_within_h > 0)),
    CONSTRAINT recommendations_rules_version_check CHECK ((rules_version > 0)),
    CONSTRAINT recommendations_terms_check CHECK (((jsonb_typeof(terms) = 'array'::text) AND (jsonb_array_length(terms) > 0)))
);


--
-- Name: TABLE recommendations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.recommendations IS 'Deterministic, explained recommendations. Every score point comes from a stored term.';


--
-- Name: reconciliation_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reconciliation_decisions (
    decision_id bigint NOT NULL,
    module text NOT NULL,
    subject_type text NOT NULL,
    subject_id text NOT NULL,
    object_type text,
    object_id text,
    relationship_type text NOT NULL,
    method text NOT NULL,
    evidence jsonb NOT NULL,
    confidence double precision,
    uncertainty jsonb,
    verification_status public.verification_status NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    algorithm_version text NOT NULL,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    batch_id text,
    supersedes_decision_id bigint,
    review_id bigint,
    CONSTRAINT decision_has_evidence CHECK (((jsonb_typeof(evidence) = 'object'::text) AND (evidence <> '{}'::jsonb))),
    CONSTRAINT experimental_is_never_verified CHECK (((relationship_type <> 'EXPERIMENTAL_ASSIGNMENT'::text) OR ((provenance_class = ANY (ARRAY['REPLAYED'::public.provenance_class, 'SYNTHETIC'::public.provenance_class])) AND (verification_status <> 'VERIFIED'::public.verification_status) AND (object_type = 'ASSET'::text)))),
    CONSTRAINT identity_never_involves_fictional CHECK (((relationship_type <> 'SAME_AS'::text) OR ((subject_type <> 'ASSET'::text) AND (object_type IS DISTINCT FROM 'ASSET'::text)))),
    CONSTRAINT inferred_is_never_verified CHECK (((provenance_class <> 'INFERRED'::public.provenance_class) OR (verification_status <> 'VERIFIED'::public.verification_status))),
    CONSTRAINT object_type_and_id_together CHECK (((object_type IS NULL) = (object_id IS NULL))),
    CONSTRAINT proximity_is_only_a_candidate CHECK (((relationship_type <> ALL (ARRAY['PROXIMITY_CANDIDATE'::text, 'EMISSION_NEAR'::text])) OR ((provenance_class = 'INFERRED'::public.provenance_class) AND (verification_status <> 'VERIFIED'::public.verification_status) AND ((method = 'GEOSPATIAL_PROXIMITY'::text) OR ((method = 'HUMAN_REVIEW'::text) AND (verification_status = 'REJECTED'::public.verification_status)))))),
    CONSTRAINT real_never_relates_to_fictional CHECK (((NOT ((subject_type = 'SOURCE_ASSET'::text) AND (object_type = 'ASSET'::text))) AND (NOT ((subject_type = 'ASSET'::text) AND (object_type = 'SOURCE_ASSET'::text))))),
    CONSTRAINT reconciliation_decisions_algorithm_version_check CHECK ((algorithm_version ~ '@[0-9]+$'::text)),
    CONSTRAINT reconciliation_decisions_confidence_check CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT reconciliation_decisions_module_check CHECK ((module = ANY (ARRAY['IDENTITY'::text, 'SEMANTIC'::text, 'GEOSPATIAL'::text, 'SCENARIO'::text]))),
    CONSTRAINT reconciliation_decisions_object_type_check CHECK ((object_type = ANY (ARRAY['SOURCE_ASSET'::text, 'ASSET'::text, 'SOURCE_RECORD'::text, 'SOURCE_SYSTEM'::text, 'MEASUREMENT_DEFINITION'::text]))),
    CONSTRAINT reconciliation_decisions_relationship_type_check CHECK ((relationship_type = ANY (ARRAY['SAME_AS'::text, 'COMPLETION_OF'::text, 'NO_CROSSWALK'::text, 'SAME_MEASUREMENT'::text, 'PROXIMITY_CANDIDATE'::text, 'EMISSION_NEAR'::text, 'EXPERIMENTAL_ASSIGNMENT'::text]))),
    CONSTRAINT reconciliation_decisions_subject_type_check CHECK ((subject_type = ANY (ARRAY['SOURCE_ASSET'::text, 'ASSET'::text, 'SOURCE_RECORD'::text, 'SOURCE_SYSTEM'::text, 'SENSOR_TAG'::text, 'OBSERVATION'::text, 'SCENARIO_RUN'::text]))),
    CONSTRAINT review_decisions_are_linked CHECK ((((method = 'HUMAN_REVIEW'::text) = (review_id IS NOT NULL)) AND ((method <> 'HUMAN_REVIEW'::text) OR (supersedes_decision_id IS NOT NULL)))),
    CONSTRAINT reviewed_identity_cites_identifier CHECK (((NOT ((relationship_type = 'SAME_AS'::text) AND (method = 'HUMAN_REVIEW'::text) AND (verification_status = 'VERIFIED'::public.verification_status))) OR (evidence ? 'authoritative_identifier'::text))),
    CONSTRAINT verified_identity_needs_identifier CHECK (((NOT ((relationship_type = ANY (ARRAY['SAME_AS'::text, 'COMPLETION_OF'::text])) AND (verification_status = 'VERIFIED'::public.verification_status))) OR (method = ANY (ARRAY['AUTHORITATIVE_IDENTIFIER'::text, 'HUMAN_REVIEW'::text])))),
    CONSTRAINT verified_measurement_needs_declared_basis CHECK (((NOT ((relationship_type = 'SAME_MEASUREMENT'::text) AND (verification_status = 'VERIFIED'::public.verification_status))) OR (method = ANY (ARRAY['PUBLISHED_DEFINITION_SAME_CLASS'::text, 'DECLARED_SYNTHETIC_DESIGN'::text])))),
    CONSTRAINT weak_methods_cannot_assert_identity CHECK ((NOT ((relationship_type = 'SAME_AS'::text) AND (method = ANY (ARRAY['NAME_SIMILARITY'::text, 'GEOSPATIAL_PROXIMITY'::text, 'UNIT_SIMILARITY'::text])) AND (verification_status <> 'REJECTED'::public.verification_status))))
);


--
-- Name: TABLE reconciliation_decisions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.reconciliation_decisions IS 'Every reconciliation outcome with its identifiers, method, evidence, status, algorithm version, and time. Unknown stays UNRESOLVED.';


--
-- Name: COLUMN reconciliation_decisions.confidence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.reconciliation_decisions.confidence IS 'Only where justified. Distance is not a probability, so proximity candidates leave this NULL.';


--
-- Name: reconciliation_decisions_decision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reconciliation_decisions_decision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reconciliation_decisions_decision_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reconciliation_decisions_decision_id_seq OWNED BY public.reconciliation_decisions.decision_id;


--
-- Name: reconciliation_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reconciliation_reviews (
    review_id bigint NOT NULL,
    decision_id bigint NOT NULL,
    reviewer text NOT NULL,
    action text NOT NULL,
    rationale text NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    reviewed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT reconciliation_reviews_action_check CHECK ((action = ANY (ARRAY['APPROVE'::text, 'REJECT'::text, 'REQUEST_EVIDENCE'::text]))),
    CONSTRAINT reconciliation_reviews_rationale_check CHECK ((length(rationale) >= 10)),
    CONSTRAINT reconciliation_reviews_reviewer_check CHECK ((reviewer <> ''::text))
);


--
-- Name: TABLE reconciliation_reviews; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.reconciliation_reviews IS 'Human review of a decision. No automatic process writes here.';


--
-- Name: reconciliation_reviews_review_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reconciliation_reviews_review_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reconciliation_reviews_review_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reconciliation_reviews_review_id_seq OWNED BY public.reconciliation_reviews.review_id;


--
-- Name: scenario_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_mappings (
    mapping_id bigint NOT NULL,
    scenario_id text NOT NULL,
    target_asset_id text NOT NULL,
    telemetry_event_id text NOT NULL,
    original_source_instance_id text NOT NULL,
    transformation_config jsonb NOT NULL,
    compatibility_assessment_id text NOT NULL,
    conditions_satisfied jsonb,
    mapping_provenance public.provenance_class NOT NULL,
    replay_start_time timestamp with time zone,
    CONSTRAINT scenario_mappings_mapping_provenance_check CHECK ((mapping_provenance = ANY (ARRAY['REPLAYED'::public.provenance_class, 'SYNTHETIC'::public.provenance_class])))
);


--
-- Name: TABLE scenario_mappings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.scenario_mappings IS 'Explicit, immutable experimental association. Never OBSERVED, and a new version means a new row.';


--
-- Name: scenario_mappings_mapping_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_mappings_mapping_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_mappings_mapping_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_mappings_mapping_id_seq OWNED BY public.scenario_mappings.mapping_id;


--
-- Name: scenario_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_runs (
    scenario_run_id text NOT NULL,
    scenario_id text NOT NULL,
    case_name text NOT NULL,
    target_asset_id text NOT NULL,
    affected_asset_id text NOT NULL,
    simulator_name text NOT NULL,
    simulator_version integer NOT NULL,
    config_sha256 text NOT NULL,
    output_sha256 text NOT NULL,
    output_uri text NOT NULL,
    random_seed bigint NOT NULL,
    sample_count integer NOT NULL,
    sampling_interval_s integer NOT NULL,
    fault_onset_offset_s integer,
    parameters jsonb NOT NULL,
    invariants jsonb NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    transformation_id text NOT NULL,
    CONSTRAINT fault_case_has_known_onset CHECK (((case_name = 'fault'::text) = (fault_onset_offset_s IS NOT NULL))),
    CONSTRAINT scenario_runs_case_name_check CHECK ((case_name = ANY (ARRAY['nominal'::text, 'fault'::text]))),
    CONSTRAINT scenario_runs_config_sha256_check CHECK ((config_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT scenario_runs_output_sha256_check CHECK ((output_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT scenario_runs_provenance_class_check CHECK ((provenance_class = 'SYNTHETIC'::public.provenance_class)),
    CONSTRAINT scenario_runs_sample_count_check CHECK ((sample_count > 0)),
    CONSTRAINT scenario_runs_sampling_interval_s_check CHECK ((sampling_interval_s > 0)),
    CONSTRAINT scenario_runs_simulator_version_check CHECK ((simulator_version > 0))
);


--
-- Name: TABLE scenario_runs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.scenario_runs IS 'One simulator run on fictional assets, with its parameters, seed, and output checksum. Always SYNTHETIC, and immutable.';


--
-- Name: scenarios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenarios (
    scenario_id text NOT NULL,
    scenario_name text NOT NULL,
    scenario_description text NOT NULL,
    target_facility_id text NOT NULL,
    scenario_version integer NOT NULL,
    random_seed bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT scenarios_scenario_version_check CHECK ((scenario_version > 0))
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version text NOT NULL,
    sha256 text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sensor_tag_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sensor_tag_mappings (
    mapping_id bigint NOT NULL,
    tag_id text NOT NULL,
    measurement_definition_id text NOT NULL,
    equipment_class_id text NOT NULL,
    reference_type public.reference_type NOT NULL,
    source_system_id text NOT NULL,
    original_unit_id text NOT NULL,
    canonical_unit_id text NOT NULL,
    conversion_method text NOT NULL,
    data_quality_state text NOT NULL,
    mapping_status public.verification_status NOT NULL,
    rationale text NOT NULL,
    valid_from date DEFAULT '-infinity'::date NOT NULL,
    valid_to date,
    CONSTRAINT sensor_tag_mappings_data_quality_state_check CHECK ((data_quality_state = ANY (ARRAY['SEMANTICS_COMPLETE'::text, 'SEMANTICS_INCOMPLETE'::text, 'NOT_ASSESSED'::text]))),
    CONSTRAINT tag_mapping_validity CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))
);


--
-- Name: TABLE sensor_tag_mappings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.sensor_tag_mappings IS 'Same-class semantic mappings. Crossing equipment domains is only possible through a compatibility assessment and an experimental scenario mapping.';


--
-- Name: sensor_tag_mappings_mapping_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sensor_tag_mappings_mapping_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sensor_tag_mappings_mapping_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sensor_tag_mappings_mapping_id_seq OWNED BY public.sensor_tag_mappings.mapping_id;


--
-- Name: sensor_tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sensor_tags (
    tag_id text NOT NULL,
    source_system_id text NOT NULL,
    native_tag_name text NOT NULL,
    canonical_metric text,
    equipment_position text NOT NULL,
    equipment_class_id text NOT NULL,
    physical_quantity text NOT NULL,
    unit_id text NOT NULL,
    pressure_reference_type public.reference_type NOT NULL,
    sampling_frequency text,
    mapping_status public.verification_status NOT NULL,
    source_description text NOT NULL,
    fictional_asset_id text,
    CONSTRAINT synthetic_sensor_has_fictional_asset CHECK (((source_system_id = 'aether_synthetic'::text) = (fictional_asset_id IS NOT NULL))),
    CONSTRAINT tag_reference_fits_quantity CHECK ((((physical_quantity = 'pressure'::text) AND (pressure_reference_type <> 'NOT_APPLICABLE'::public.reference_type)) OR ((physical_quantity <> 'pressure'::text) AND (pressure_reference_type = 'NOT_APPLICABLE'::public.reference_type))))
);


--
-- Name: TABLE sensor_tags; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.sensor_tags IS 'Native tags as published by the source, with their physical class and original unit.';


--
-- Name: COLUMN sensor_tags.fictional_asset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sensor_tags.fictional_asset_id IS 'The fictional asset a synthetic sensor is installed on. Always NULL for source tags.';


--
-- Name: shared_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shared_events (
    event_id text NOT NULL,
    schema_version integer NOT NULL,
    domain text NOT NULL,
    event_kind text NOT NULL,
    event_class text NOT NULL,
    source_system_id text NOT NULL,
    telemetry_event_id text,
    scenario_id text,
    scenario_run_id text,
    target_asset_id text,
    affected_asset_id text,
    onset_offset_s integer,
    evidence jsonb NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    transformation_id text NOT NULL,
    CONSTRAINT aether_events_are_synthetic_and_scoped CHECK (((domain <> 'AETHER_SYNTHETIC'::text) OR ((provenance_class = 'SYNTHETIC'::public.provenance_class) AND (source_system_id = 'aether_synthetic'::text) AND (scenario_id IS NOT NULL) AND (scenario_run_id IS NOT NULL) AND (target_asset_id IS NOT NULL) AND (telemetry_event_id IS NULL) AND (event_kind <> 'SOURCE_LABEL'::text)))),
    CONSTRAINT benchmark_events_stay_independent CHECK (((domain <> 'OFFSHORE_BENCHMARK'::text) OR ((provenance_class = ANY (ARRAY['DERIVED'::public.provenance_class, 'SYNTHETIC'::public.provenance_class])) AND (source_system_id = 'petrobras_3w'::text) AND (telemetry_event_id IS NOT NULL) AND (event_kind = 'SOURCE_LABEL'::text) AND (scenario_id IS NULL) AND (scenario_run_id IS NULL) AND (target_asset_id IS NULL) AND (affected_asset_id IS NULL)))),
    CONSTRAINT shared_events_domain_check CHECK ((domain = ANY (ARRAY['AETHER_SYNTHETIC'::text, 'OFFSHORE_BENCHMARK'::text]))),
    CONSTRAINT shared_events_event_kind_check CHECK ((event_kind = ANY (ARRAY['SOURCE_LABEL'::text, 'KNOWN_SYNTHETIC_ONSET'::text, 'INTEGRATION_PROOF_RULE'::text]))),
    CONSTRAINT shared_events_evidence_check CHECK ((evidence <> '{}'::jsonb)),
    CONSTRAINT shared_events_onset_offset_s_check CHECK ((onset_offset_s >= 0)),
    CONSTRAINT shared_events_schema_version_check CHECK ((schema_version > 0))
);


--
-- Name: TABLE shared_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.shared_events IS 'One event contract for both domains, which stay separate. It carries no detection accuracy.';


--
-- Name: source_asset_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_asset_history (
    history_id bigint NOT NULL,
    source_asset_id text NOT NULL,
    valid_from date NOT NULL,
    valid_to date,
    operator_code text,
    status_code text,
    well_type_code text,
    reported_latitude double precision,
    reported_longitude double precision,
    reported_datum_label text,
    attributes jsonb DEFAULT '{}'::jsonb NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    batch_id text NOT NULL,
    transformation_id text NOT NULL,
    source_record_key text NOT NULL,
    CONSTRAINT history_validity CHECK (((valid_to IS NULL) OR (valid_to > valid_from))),
    CONSTRAINT source_asset_history_provenance_class_check CHECK ((provenance_class = 'OBSERVED'::public.provenance_class))
);


--
-- Name: TABLE source_asset_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.source_asset_history IS 'Temporal well records. OCD''s 9999-12-31 sentinel is stored as an open-ended valid_to.';


--
-- Name: source_asset_history_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_asset_history_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_asset_history_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_asset_history_history_id_seq OWNED BY public.source_asset_history.history_id;


--
-- Name: source_assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_assets (
    source_asset_id text NOT NULL,
    source_system_id text NOT NULL,
    parent_source_asset_id text,
    asset_type text NOT NULL,
    external_identifier text NOT NULL,
    asset_name text,
    equipment_class_id text NOT NULL,
    operating_status text,
    reported_latitude double precision,
    reported_longitude double precision,
    reported_datum_label text,
    geometry public.geometry(Point,4269),
    spatial_status public.spatial_status NOT NULL,
    attributes jsonb DEFAULT '{}'::jsonb NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    batch_id text NOT NULL,
    transformation_id text NOT NULL,
    source_record_key text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT completion_has_parent CHECK (((asset_type = 'WELL_COMPLETION'::text) = (parent_source_asset_id IS NOT NULL))),
    CONSTRAINT geometry_only_when_usable CHECK (((spatial_status = 'USABLE'::public.spatial_status) = (geometry IS NOT NULL))),
    CONSTRAINT source_assets_asset_type_check CHECK ((asset_type = ANY (ARRAY['WELL'::text, 'WELL_COMPLETION'::text]))),
    CONSTRAINT source_assets_provenance_class_check CHECK ((provenance_class = 'OBSERVED'::public.provenance_class)),
    CONSTRAINT usable_geometry_is_valid CHECK (((geometry IS NULL) OR (public.st_isvalid(geometry) AND ((public.st_y(geometry) >= ('-90'::integer)::double precision) AND (public.st_y(geometry) <= (90)::double precision)) AND ((public.st_x(geometry) >= ('-180'::integer)::double precision) AND (public.st_x(geometry) <= (180)::double precision)))))
);


--
-- Name: TABLE source_assets; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.source_assets IS 'Real entities named by a source. Always OBSERVED, never part of AETHER Field.';


--
-- Name: COLUMN source_assets.reported_latitude; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_assets.reported_latitude IS 'As reported by the source. Never corrected, even when quarantined.';


--
-- Name: COLUMN source_assets.geometry; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_assets.geometry IS 'NAD83 point, present only when spatial_status is USABLE.';


--
-- Name: source_event_classes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_event_classes (
    source_system_id text NOT NULL,
    event_label smallint NOT NULL,
    event_name text NOT NULL,
    description text NOT NULL,
    has_transient boolean
);


--
-- Name: source_identifiers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_identifiers (
    identifier_id bigint NOT NULL,
    source_system_id text NOT NULL,
    canonical_asset_id text,
    external_identifier text NOT NULL,
    identifier_type text NOT NULL,
    valid_from date DEFAULT '-infinity'::date NOT NULL,
    valid_to date,
    verification_status public.verification_status NOT NULL,
    CONSTRAINT identifier_validity CHECK (((valid_to IS NULL) OR (valid_to > valid_from))),
    CONSTRAINT verified_identifier_has_asset CHECK (((verification_status <> 'VERIFIED'::public.verification_status) OR (canonical_asset_id IS NOT NULL)))
);


--
-- Name: TABLE source_identifiers; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.source_identifiers IS 'Source identifiers for real assets. canonical_asset_id references source_assets only, so no real identifier can resolve to a fictional asset.';


--
-- Name: source_identifiers_identifier_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_identifiers_identifier_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_identifiers_identifier_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_identifiers_identifier_id_seq OWNED BY public.source_identifiers.identifier_id;


--
-- Name: source_reconciliation_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_reconciliation_evidence (
    evidence_id bigint NOT NULL,
    source_asset_id text NOT NULL,
    batch_id text NOT NULL,
    field_name text NOT NULL,
    channel_a text NOT NULL,
    value_a text,
    channel_b text NOT NULL,
    value_b text,
    outcome text NOT NULL,
    channels_are_independent boolean NOT NULL,
    method_version text NOT NULL,
    CONSTRAINT source_reconciliation_evidence_outcome_check CHECK ((outcome = ANY (ARRAY['AGREE'::text, 'CONFLICT'::text, 'MISSING'::text])))
);


--
-- Name: TABLE source_reconciliation_evidence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.source_reconciliation_evidence IS 'Field-level comparisons between channels. channels_are_independent records whether agreement can count as confirmation. OCD ArcGIS and FTP are not independent.';


--
-- Name: source_reconciliation_evidence_evidence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_reconciliation_evidence_evidence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_reconciliation_evidence_evidence_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_reconciliation_evidence_evidence_id_seq OWNED BY public.source_reconciliation_evidence.evidence_id;


--
-- Name: source_systems; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_systems (
    source_system_id text NOT NULL,
    provider text NOT NULL,
    source_url text NOT NULL,
    source_version text,
    license text NOT NULL,
    retrieval_timestamp timestamp with time zone,
    usage_constraints text NOT NULL,
    is_project_generated boolean DEFAULT false NOT NULL
);


--
-- Name: TABLE source_systems; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.source_systems IS 'Each independent origin of data, including the project-generated synthetic source.';


--
-- Name: telemetry_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.telemetry_events (
    event_id text NOT NULL,
    source_system_id text NOT NULL,
    source_instance_id text NOT NULL,
    source_asset_id text,
    source_event_label smallint NOT NULL,
    source_event_class text NOT NULL,
    start_timestamp timestamp without time zone NOT NULL,
    end_timestamp timestamp without time zone NOT NULL,
    real_or_simulated_source public.instance_origin NOT NULL,
    observation_count integer NOT NULL,
    parquet_uri text NOT NULL,
    dataset_version text NOT NULL,
    upstream_checksum text NOT NULL,
    provenance_class public.provenance_class NOT NULL,
    batch_id text NOT NULL,
    transformation_id text NOT NULL,
    CONSTRAINT generated_instances_are_synthetic CHECK (((real_or_simulated_source = 'REAL'::public.instance_origin) OR (provenance_class = 'SYNTHETIC'::public.provenance_class))),
    CONSTRAINT only_real_instances_are_observed CHECK (((real_or_simulated_source = 'REAL'::public.instance_origin) = (provenance_class = 'OBSERVED'::public.provenance_class))),
    CONSTRAINT real_instance_has_source_well CHECK (((real_or_simulated_source = 'REAL'::public.instance_origin) = (source_asset_id IS NOT NULL))),
    CONSTRAINT telemetry_events_observation_count_check CHECK ((observation_count >= 0)),
    CONSTRAINT telemetry_time_order CHECK ((end_timestamp >= start_timestamp))
);


--
-- Name: TABLE telemetry_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.telemetry_events IS 'One row per 3W instance. Instance IDs repeat across classes, so identity includes the event label. Timestamps carry no stated time zone.';


--
-- Name: transformations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transformations (
    transformation_id text NOT NULL,
    name text NOT NULL,
    version integer NOT NULL,
    code_reference text NOT NULL,
    description text NOT NULL,
    input_provenance public.provenance_class[] NOT NULL,
    output_provenance public.provenance_class NOT NULL,
    alters_values boolean NOT NULL,
    CONSTRAINT observed_output_is_unaltered CHECK (((output_provenance <> 'OBSERVED'::public.provenance_class) OR ((input_provenance = ARRAY['OBSERVED'::public.provenance_class]) AND (NOT alters_values)))),
    CONSTRAINT synthetic_input_cannot_become_derived CHECK (((output_provenance <> ALL (ARRAY['DERIVED'::public.provenance_class, 'OBSERVED'::public.provenance_class])) OR (NOT ('SYNTHETIC'::public.provenance_class = ANY (input_provenance))))),
    CONSTRAINT transformations_input_provenance_check CHECK ((cardinality(input_provenance) > 0)),
    CONSTRAINT transformations_version_check CHECK ((version > 0))
);


--
-- Name: TABLE transformations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.transformations IS 'Provenance as a property of the process. Canonical rows reference this with a composite key, so a row cannot claim a class its transformation does not produce.';


--
-- Name: unit_conversions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unit_conversions (
    from_unit_id text NOT NULL,
    to_unit_id text NOT NULL,
    physical_quantity text NOT NULL,
    factor double precision NOT NULL,
    term double precision DEFAULT 0 NOT NULL,
    method text NOT NULL
);


--
-- Name: TABLE unit_conversions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.unit_conversions IS 'value_out = value_in * factor + term. Both units must measure the same quantity. Gauge-to-absolute changes are not unit conversions and are not representable here.';


--
-- Name: units; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.units (
    unit_id text NOT NULL,
    physical_quantity text NOT NULL,
    description text NOT NULL
);


--
-- Name: v_current_reconciliation_decisions; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_current_reconciliation_decisions AS
 SELECT decision_id,
    module,
    subject_type,
    subject_id,
    object_type,
    object_id,
    relationship_type,
    method,
    evidence,
    confidence,
    uncertainty,
    verification_status,
    provenance_class,
    algorithm_version,
    decided_at,
    batch_id,
    supersedes_decision_id,
    review_id
   FROM public.reconciliation_decisions d
  WHERE (NOT (EXISTS ( SELECT 1
           FROM public.reconciliation_decisions later
          WHERE (later.supersedes_decision_id = d.decision_id))));


--
-- Name: VIEW v_current_reconciliation_decisions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_current_reconciliation_decisions IS 'Decisions not yet superseded by a reviewed decision.';


--
-- Name: v_open_quality_exceptions; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_open_quality_exceptions AS
 SELECT exception_id,
    exception_type,
    severity,
    dataset,
    source_asset_id,
    source_record_key,
    disposition,
    status,
    decision_rationale
   FROM public.data_quality_exceptions
  WHERE (status = 'OPEN'::text);


--
-- Name: v_production_lineage; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_production_lineage AS
 SELECT p.record_id,
    p.reporting_entity_id,
    parent.external_identifier AS api_number,
    p.reporting_period,
    p.product_kind,
    p.reported_volume,
    p.unit_id,
    p.source_effective_at,
    p.provenance_class,
    p.source_record_key,
    p.original_record_uri,
    t.transformation_id,
    t.code_reference,
    t.alters_values,
    b.batch_id,
    b.source_system_id,
    b.source_version,
    b.manifest_uri,
    f.path AS raw_file_path,
    f.sha256 AS raw_file_sha256,
    f.source_url AS raw_file_source_url
   FROM (((((public.production_records p
     JOIN public.source_assets c ON ((c.source_asset_id = p.reporting_entity_id)))
     JOIN public.source_assets parent ON ((parent.source_asset_id = c.parent_source_asset_id)))
     JOIN public.transformations t ON ((t.transformation_id = p.transformation_id)))
     JOIN public.ingestion_batches b ON ((b.batch_id = p.batch_id)))
     JOIN public.batch_files f ON (((f.batch_id = p.batch_id) AND (f.path = p.original_record_uri))));


--
-- Name: v_production_wide; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_production_wide AS
 SELECT source_system_id,
    reporting_entity_id,
    reporting_grain,
    reporting_period,
    max(reported_volume) FILTER (WHERE (product_kind = 'O'::text)) AS oil_volume_bbl,
    max(reported_volume) FILTER (WHERE (product_kind = 'G'::text)) AS gas_volume_mcf_15025psia_60f,
    max(reported_volume) FILTER (WHERE (product_kind = 'W'::text)) AS water_volume_bbl
   FROM public.production_records
  GROUP BY source_system_id, reporting_entity_id, reporting_grain, reporting_period;


--
-- Name: VIEW v_production_wide; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_production_wide IS 'Oil, gas, and water per completion and month. A missing product stays NULL, never zero.';


--
-- Name: v_reconciliation_review_queue; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_reconciliation_review_queue AS
 SELECT decision_id,
    module,
    relationship_type,
    subject_id,
    object_id,
    method,
    verification_status,
    decided_at
   FROM public.v_current_reconciliation_decisions d
  WHERE ((verification_status = ANY (ARRAY['UNVERIFIED'::public.verification_status, 'UNRESOLVED'::public.verification_status])) AND (relationship_type <> 'EXPERIMENTAL_ASSIGNMENT'::text) AND (NOT (EXISTS ( SELECT 1
           FROM public.reconciliation_reviews r
          WHERE (r.decision_id = d.decision_id)))));


--
-- Name: VIEW v_reconciliation_review_queue; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_reconciliation_review_queue IS 'Open decisions awaiting human review. Nothing leaves this queue automatically.';


--
-- Name: v_spatially_usable_source_assets; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_spatially_usable_source_assets AS
 SELECT source_asset_id,
    source_system_id,
    asset_type,
    external_identifier,
    operating_status,
    geometry
   FROM public.source_assets
  WHERE ((spatial_status = 'USABLE'::public.spatial_status) AND (geometry IS NOT NULL));


--
-- Name: VIEW v_spatially_usable_source_assets; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_spatially_usable_source_assets IS 'The only spatial population for analytics. Excludes quarantined coordinates and unresolved datums.';


--
-- Name: v_synthetic_provenance_chain; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_synthetic_provenance_chain AS
 SELECT o.observation_id,
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
    (((o.provenance_class = 'SYNTHETIC'::public.provenance_class) AND (tr.output_provenance = 'SYNTHETIC'::public.provenance_class) AND a.is_fictional AND (l.asset_id = t.fictional_asset_id) AND (l.relationship_type = 'EXPERIMENTAL_SCENARIO_LINK'::text) AND (r.scenario_id = o.scenario_id) AND (r.simulator_version IS NOT NULL) AND (r.config_sha256 IS NOT NULL) AND (r.output_sha256 IS NOT NULL)) IS TRUE) AS chain_complete
   FROM ((((((public.observations o
     LEFT JOIN public.sensor_tags t ON ((t.tag_id = o.sensor_tag_id)))
     LEFT JOIN public.assets a ON ((a.asset_id = t.fictional_asset_id)))
     LEFT JOIN public.asset_observation_links l ON (((l.observation_id = o.observation_id) AND (l.asset_id IS NOT NULL))))
     LEFT JOIN public.scenario_runs r ON ((r.scenario_run_id = o.scenario_run_id)))
     LEFT JOIN public.scenarios s ON ((s.scenario_id = o.scenario_id)))
     LEFT JOIN public.transformations tr ON ((tr.transformation_id = o.transformation_id)))
  WHERE (o.source_system_id = 'aether_synthetic'::text);


--
-- Name: VIEW v_synthetic_provenance_chain; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_synthetic_provenance_chain IS 'Each synthetic observation with its asset, sensor, scenario, run, simulator version, and parameter set.';


--
-- Name: v_tag_semantics; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_tag_semantics AS
 SELECT s.tag_id,
    s.native_tag_name AS original_source_tag,
    s.physical_quantity,
    s.equipment_position AS equipment_location,
    s.pressure_reference_type AS measurement_reference_type,
    s.unit_id AS original_unit,
    m.canonical_unit_id AS canonical_unit,
    m.conversion_method,
    s.source_system_id AS source_system,
    m.data_quality_state,
    m.measurement_definition_id,
    s.equipment_class_id
   FROM (public.sensor_tags s
     LEFT JOIN public.sensor_tag_mappings m ON ((m.tag_id = s.tag_id)));


--
-- Name: VIEW v_tag_semantics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_tag_semantics IS 'The nine required semantic attributes for each sensor measurement.';


--
-- Name: v_telemetry_lineage; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_telemetry_lineage AS
 SELECT e.event_id,
    e.source_instance_id,
    e.source_event_label,
    e.source_event_class,
    e.real_or_simulated_source,
    e.provenance_class,
    e.source_asset_id,
    e.dataset_version,
    e.parquet_uri,
    t.transformation_id,
    t.code_reference,
    b.batch_id,
    b.manifest_uri,
    f.sha256 AS raw_file_sha256,
    f.upstream_checksum,
    f.source_url AS raw_file_source_url
   FROM (((public.telemetry_events e
     JOIN public.transformations t ON ((t.transformation_id = e.transformation_id)))
     JOIN public.ingestion_batches b ON ((b.batch_id = e.batch_id)))
     JOIN public.batch_files f ON (((f.batch_id = e.batch_id) AND (f.path = e.parquet_uri))));


--
-- Name: work_order_transitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_order_transitions (
    transition_id bigint NOT NULL,
    work_order_id bigint NOT NULL,
    sequence integer NOT NULL,
    decision text NOT NULL,
    from_status text,
    to_status text NOT NULL,
    actor_id text NOT NULL,
    actor_kind text NOT NULL,
    actor_role text NOT NULL,
    justification text NOT NULL,
    decided_at timestamp with time zone NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT allowed_transition CHECK (((((((((decision = 'CREATE'::text) AND (COALESCE(from_status, '-'::text) = '-'::text) AND (to_status = 'RECOMMENDED'::text)) OR ((decision = 'APPROVE'::text) AND (COALESCE(from_status, '-'::text) = 'RECOMMENDED'::text) AND (to_status = 'APPROVED'::text))) OR ((decision = 'REJECT'::text) AND (COALESCE(from_status, '-'::text) = 'RECOMMENDED'::text) AND (to_status = 'REJECTED'::text))) OR ((decision = 'REQUEST_EVIDENCE'::text) AND (COALESCE(from_status, '-'::text) = 'RECOMMENDED'::text) AND (to_status = 'NEEDS_EVIDENCE'::text))) OR ((decision = 'RESUBMIT'::text) AND (COALESCE(from_status, '-'::text) = 'NEEDS_EVIDENCE'::text) AND (to_status = 'RECOMMENDED'::text))) OR ((decision = 'REJECT'::text) AND (COALESCE(from_status, '-'::text) = 'NEEDS_EVIDENCE'::text) AND (to_status = 'REJECTED'::text))) OR ((decision = 'COMPLETE'::text) AND (COALESCE(from_status, '-'::text) = 'APPROVED'::text) AND (to_status = 'COMPLETED'::text)))),
    CONSTRAINT only_the_engine_creates CHECK (((decision = 'CREATE'::text) = (actor_kind = 'SYSTEM'::text))),
    CONSTRAINT supervisor_decides CHECK (((decision <> ALL (ARRAY['APPROVE'::text, 'REJECT'::text, 'REQUEST_EVIDENCE'::text])) OR (actor_role = 'MAINTENANCE_SUPERVISOR'::text))),
    CONSTRAINT work_order_transitions_actor_id_check CHECK ((length(btrim(actor_id)) > 0)),
    CONSTRAINT work_order_transitions_actor_kind_check CHECK ((actor_kind = ANY (ARRAY['HUMAN'::text, 'SCRIPTED_DEMO'::text, 'SYSTEM'::text]))),
    CONSTRAINT work_order_transitions_decision_check CHECK ((decision = ANY (ARRAY['CREATE'::text, 'APPROVE'::text, 'REJECT'::text, 'REQUEST_EVIDENCE'::text, 'RESUBMIT'::text, 'COMPLETE'::text]))),
    CONSTRAINT work_order_transitions_justification_check CHECK ((length(btrim(justification)) > 0)),
    CONSTRAINT work_order_transitions_sequence_check CHECK ((sequence >= 0))
);


--
-- Name: TABLE work_order_transitions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.work_order_transitions IS 'Authoritative work-order history. SCRIPTED_DEMO actors stand in for people in demonstration runs and are never human decisions.';


--
-- Name: work_order_transitions_transition_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.work_order_transitions_transition_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: work_order_transitions_transition_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.work_order_transitions_transition_id_seq OWNED BY public.work_order_transitions.transition_id;


--
-- Name: work_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_orders (
    work_order_id bigint NOT NULL,
    scenario_id text NOT NULL,
    asset_id text NOT NULL,
    recommended_action text NOT NULL,
    severity text NOT NULL,
    priority integer NOT NULL,
    status text NOT NULL,
    estimated_cost numeric(12,2),
    evidence_reference text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    external_id text,
    recommendation_id text,
    priority_band text,
    CONSTRAINT work_orders_priority_band_check CHECK ((priority_band = ANY (ARRAY['P1'::text, 'P2'::text, 'P3'::text]))),
    CONSTRAINT work_orders_status_check CHECK ((status = ANY (ARRAY['RECOMMENDED'::text, 'APPROVED'::text, 'REJECTED'::text, 'NEEDS_EVIDENCE'::text, 'COMPLETED'::text])))
);


--
-- Name: TABLE work_orders; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.work_orders IS 'Simulated work on fictional assets. A work order requires a scenario and cannot point at a real well.';


--
-- Name: work_orders_work_order_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.work_orders_work_order_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: work_orders_work_order_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.work_orders_work_order_id_seq OWNED BY public.work_orders.work_order_id;


--
-- Name: anomaly_predictions prediction_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_predictions ALTER COLUMN prediction_id SET DEFAULT nextval('public.anomaly_predictions_prediction_id_seq'::regclass);


--
-- Name: approval_events approval_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_events ALTER COLUMN approval_id SET DEFAULT nextval('public.approval_events_approval_id_seq'::regclass);


--
-- Name: asset_observation_links link_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_observation_links ALTER COLUMN link_id SET DEFAULT nextval('public.asset_observation_links_link_id_seq'::regclass);


--
-- Name: asset_relationships relationship_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_relationships ALTER COLUMN relationship_id SET DEFAULT nextval('public.asset_relationships_relationship_id_seq'::regclass);


--
-- Name: audit_events event_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events ALTER COLUMN event_id SET DEFAULT nextval('public.audit_events_event_id_seq'::regclass);


--
-- Name: data_quality_exceptions exception_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_exceptions ALTER COLUMN exception_id SET DEFAULT nextval('public.data_quality_exceptions_exception_id_seq'::regclass);


--
-- Name: inspection_observations inspection_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_observations ALTER COLUMN inspection_id SET DEFAULT nextval('public.inspection_observations_inspection_id_seq'::regclass);


--
-- Name: observations observation_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations ALTER COLUMN observation_id SET DEFAULT nextval('public.observations_observation_id_seq'::regclass);


--
-- Name: production_records record_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_records ALTER COLUMN record_id SET DEFAULT nextval('public.production_records_record_id_seq'::regclass);


--
-- Name: reconciliation_decisions decision_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_decisions ALTER COLUMN decision_id SET DEFAULT nextval('public.reconciliation_decisions_decision_id_seq'::regclass);


--
-- Name: reconciliation_reviews review_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_reviews ALTER COLUMN review_id SET DEFAULT nextval('public.reconciliation_reviews_review_id_seq'::regclass);


--
-- Name: scenario_mappings mapping_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_mappings ALTER COLUMN mapping_id SET DEFAULT nextval('public.scenario_mappings_mapping_id_seq'::regclass);


--
-- Name: sensor_tag_mappings mapping_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tag_mappings ALTER COLUMN mapping_id SET DEFAULT nextval('public.sensor_tag_mappings_mapping_id_seq'::regclass);


--
-- Name: source_asset_history history_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_asset_history ALTER COLUMN history_id SET DEFAULT nextval('public.source_asset_history_history_id_seq'::regclass);


--
-- Name: source_identifiers identifier_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_identifiers ALTER COLUMN identifier_id SET DEFAULT nextval('public.source_identifiers_identifier_id_seq'::regclass);


--
-- Name: source_reconciliation_evidence evidence_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_reconciliation_evidence ALTER COLUMN evidence_id SET DEFAULT nextval('public.source_reconciliation_evidence_evidence_id_seq'::regclass);


--
-- Name: work_order_transitions transition_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_order_transitions ALTER COLUMN transition_id SET DEFAULT nextval('public.work_order_transitions_transition_id_seq'::regclass);


--
-- Name: work_orders work_order_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders ALTER COLUMN work_order_id SET DEFAULT nextval('public.work_orders_work_order_id_seq'::regclass);


--
-- Name: anomaly_predictions anomaly_predictions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_predictions
    ADD CONSTRAINT anomaly_predictions_pkey PRIMARY KEY (prediction_id);


--
-- Name: approval_events approval_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_events
    ADD CONSTRAINT approval_events_pkey PRIMARY KEY (approval_id);


--
-- Name: asset_observation_links asset_observation_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_observation_links
    ADD CONSTRAINT asset_observation_links_pkey PRIMARY KEY (link_id);


--
-- Name: asset_relationships asset_relationships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_relationships
    ADD CONSTRAINT asset_relationships_pkey PRIMARY KEY (relationship_id);


--
-- Name: assets assets_asset_id_equipment_class_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_asset_id_equipment_class_id_key UNIQUE (asset_id, equipment_class_id);


--
-- Name: assets assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_pkey PRIMARY KEY (asset_id);


--
-- Name: audit_events audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (event_id);


--
-- Name: batch_files batch_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batch_files
    ADD CONSTRAINT batch_files_pkey PRIMARY KEY (batch_id, path);


--
-- Name: data_quality_exceptions data_quality_exceptions_batch_id_rule_id_source_record_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_exceptions
    ADD CONSTRAINT data_quality_exceptions_batch_id_rule_id_source_record_key_key UNIQUE (batch_id, rule_id, source_record_key);


--
-- Name: data_quality_exceptions data_quality_exceptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_exceptions
    ADD CONSTRAINT data_quality_exceptions_pkey PRIMARY KEY (exception_id);


--
-- Name: detector_alarms detector_alarms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detector_alarms
    ADD CONSTRAINT detector_alarms_pkey PRIMARY KEY (alarm_id);


--
-- Name: domain_boundaries domain_boundaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_boundaries
    ADD CONSTRAINT domain_boundaries_pkey PRIMARY KEY (source_system_id, target_domain);


--
-- Name: domain_compatibility_assessments domain_compatibility_assessme_source_system_id_subject_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_compatibility_assessments
    ADD CONSTRAINT domain_compatibility_assessme_source_system_id_subject_type_key UNIQUE (source_system_id, subject_type, subject_id, target_equipment_class_id, assessment_version);


--
-- Name: domain_compatibility_assessments domain_compatibility_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_compatibility_assessments
    ADD CONSTRAINT domain_compatibility_assessments_pkey PRIMARY KEY (assessment_id);


--
-- Name: domain_compatibility_requirements domain_compatibility_requirements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_compatibility_requirements
    ADD CONSTRAINT domain_compatibility_requirements_pkey PRIMARY KEY (requirement_id);


--
-- Name: equipment_classes equipment_classes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment_classes
    ADD CONSTRAINT equipment_classes_pkey PRIMARY KEY (equipment_class_id);


--
-- Name: equipment_measurement_capabilities equipment_measurement_capabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment_measurement_capabilities
    ADD CONSTRAINT equipment_measurement_capabilities_pkey PRIMARY KEY (equipment_class_id, measurement_definition_id);


--
-- Name: equipment_relationship_rules equipment_relationship_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment_relationship_rules
    ADD CONSTRAINT equipment_relationship_rules_pkey PRIMARY KEY (source_asset_type, relationship_type, target_asset_type);


--
-- Name: facilities facilities_facility_id_is_fictional_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facilities
    ADD CONSTRAINT facilities_facility_id_is_fictional_key UNIQUE (facility_id, is_fictional);


--
-- Name: facilities facilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facilities
    ADD CONSTRAINT facilities_pkey PRIMARY KEY (facility_id);


--
-- Name: source_asset_history history_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_asset_history
    ADD CONSTRAINT history_no_overlap EXCLUDE USING gist (source_asset_id WITH =, daterange(valid_from, valid_to) WITH &&);


--
-- Name: source_identifiers identifier_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_identifiers
    ADD CONSTRAINT identifier_no_overlap EXCLUDE USING gist (source_system_id WITH =, identifier_type WITH =, external_identifier WITH =, daterange(valid_from, valid_to) WITH &&);


--
-- Name: ingestion_batches ingestion_batches_batch_id_source_system_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_batches
    ADD CONSTRAINT ingestion_batches_batch_id_source_system_id_key UNIQUE (batch_id, source_system_id);


--
-- Name: ingestion_batches ingestion_batches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_batches
    ADD CONSTRAINT ingestion_batches_pkey PRIMARY KEY (batch_id);


--
-- Name: inspection_observations inspection_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_observations
    ADD CONSTRAINT inspection_observations_pkey PRIMARY KEY (inspection_id);


--
-- Name: inspection_requests inspection_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_requests
    ADD CONSTRAINT inspection_requests_pkey PRIMARY KEY (request_id);


--
-- Name: inspection_review_events inspection_review_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_review_events
    ADD CONSTRAINT inspection_review_events_pkey PRIMARY KEY (review_id);


--
-- Name: measurement_definitions measurement_definitions_measurement_definition_id_equipment_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.measurement_definitions
    ADD CONSTRAINT measurement_definitions_measurement_definition_id_equipment_key UNIQUE (measurement_definition_id, equipment_class_id, reference_type, canonical_unit_id);


--
-- Name: measurement_definitions measurement_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.measurement_definitions
    ADD CONSTRAINT measurement_definitions_pkey PRIMARY KEY (measurement_definition_id);


--
-- Name: observations observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_pkey PRIMARY KEY (observation_id);


--
-- Name: observations observations_source_system_id_source_record_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_source_system_id_source_record_id_key UNIQUE (source_system_id, source_record_id);


--
-- Name: physical_connection_rules physical_connection_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_connection_rules
    ADD CONSTRAINT physical_connection_rules_pkey PRIMARY KEY (edge_type, from_node_type, to_node_type);


--
-- Name: physical_edges physical_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_edges
    ADD CONSTRAINT physical_edges_pkey PRIMARY KEY (edge_id);


--
-- Name: physical_nodes physical_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_nodes
    ADD CONSTRAINT physical_nodes_pkey PRIMARY KEY (node_id);


--
-- Name: production_records production_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_records
    ADD CONSTRAINT production_records_pkey PRIMARY KEY (record_id);


--
-- Name: production_records production_records_reporting_entity_id_reporting_period_pro_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_records
    ADD CONSTRAINT production_records_reporting_entity_id_reporting_period_pro_key UNIQUE (reporting_entity_id, reporting_period, product_kind);


--
-- Name: production_unit_rules production_unit_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_unit_rules
    ADD CONSTRAINT production_unit_rules_pkey PRIMARY KEY (source_system_id, product_kind);


--
-- Name: production_unit_rules production_unit_rules_source_system_id_product_kind_unit_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_unit_rules
    ADD CONSTRAINT production_unit_rules_source_system_id_product_kind_unit_id_key UNIQUE (source_system_id, product_kind, unit_id);


--
-- Name: recommendations recommendations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendations
    ADD CONSTRAINT recommendations_pkey PRIMARY KEY (recommendation_id);


--
-- Name: reconciliation_decisions reconciliation_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_decisions
    ADD CONSTRAINT reconciliation_decisions_pkey PRIMARY KEY (decision_id);


--
-- Name: reconciliation_reviews reconciliation_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_reviews
    ADD CONSTRAINT reconciliation_reviews_pkey PRIMARY KEY (review_id);


--
-- Name: asset_relationships relationship_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_relationships
    ADD CONSTRAINT relationship_no_overlap EXCLUDE USING gist (source_asset_id WITH =, target_asset_id WITH =, relationship_type WITH =, daterange(effective_from, effective_to) WITH &&);


--
-- Name: scenario_mappings scenario_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_mappings
    ADD CONSTRAINT scenario_mappings_pkey PRIMARY KEY (mapping_id);


--
-- Name: scenario_mappings scenario_mappings_scenario_id_target_asset_id_telemetry_eve_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_mappings
    ADD CONSTRAINT scenario_mappings_scenario_id_target_asset_id_telemetry_eve_key UNIQUE (scenario_id, target_asset_id, telemetry_event_id);


--
-- Name: scenario_runs scenario_run_scenario_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_runs
    ADD CONSTRAINT scenario_run_scenario_unique UNIQUE (scenario_run_id, scenario_id);


--
-- Name: scenario_runs scenario_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_runs
    ADD CONSTRAINT scenario_runs_pkey PRIMARY KEY (scenario_run_id);


--
-- Name: scenario_runs scenario_runs_scenario_id_case_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_runs
    ADD CONSTRAINT scenario_runs_scenario_id_case_name_key UNIQUE (scenario_id, case_name);


--
-- Name: scenarios scenarios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenarios
    ADD CONSTRAINT scenarios_pkey PRIMARY KEY (scenario_id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: sensor_tag_mappings sensor_tag_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tag_mappings
    ADD CONSTRAINT sensor_tag_mappings_pkey PRIMARY KEY (mapping_id);


--
-- Name: sensor_tags sensor_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tags
    ADD CONSTRAINT sensor_tags_pkey PRIMARY KEY (tag_id);


--
-- Name: sensor_tags sensor_tags_source_system_id_native_tag_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tags
    ADD CONSTRAINT sensor_tags_source_system_id_native_tag_name_key UNIQUE (source_system_id, native_tag_name);


--
-- Name: sensor_tags sensor_tags_tag_id_equipment_class_id_pressure_reference_ty_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tags
    ADD CONSTRAINT sensor_tags_tag_id_equipment_class_id_pressure_reference_ty_key UNIQUE (tag_id, equipment_class_id, pressure_reference_type, unit_id);


--
-- Name: shared_events shared_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_events
    ADD CONSTRAINT shared_events_pkey PRIMARY KEY (event_id);


--
-- Name: source_asset_history source_asset_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_asset_history
    ADD CONSTRAINT source_asset_history_pkey PRIMARY KEY (history_id);


--
-- Name: source_assets source_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_assets
    ADD CONSTRAINT source_assets_pkey PRIMARY KEY (source_asset_id);


--
-- Name: source_assets source_assets_source_asset_id_source_system_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_assets
    ADD CONSTRAINT source_assets_source_asset_id_source_system_id_key UNIQUE (source_asset_id, source_system_id);


--
-- Name: source_assets source_assets_source_system_id_asset_type_external_identifi_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_assets
    ADD CONSTRAINT source_assets_source_system_id_asset_type_external_identifi_key UNIQUE (source_system_id, asset_type, external_identifier);


--
-- Name: source_event_classes source_event_classes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_event_classes
    ADD CONSTRAINT source_event_classes_pkey PRIMARY KEY (source_system_id, event_label);


--
-- Name: source_event_classes source_event_classes_source_system_id_event_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_event_classes
    ADD CONSTRAINT source_event_classes_source_system_id_event_name_key UNIQUE (source_system_id, event_name);


--
-- Name: source_identifiers source_identifiers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_identifiers
    ADD CONSTRAINT source_identifiers_pkey PRIMARY KEY (identifier_id);


--
-- Name: source_reconciliation_evidence source_reconciliation_evidenc_batch_id_source_asset_id_fiel_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_reconciliation_evidence
    ADD CONSTRAINT source_reconciliation_evidenc_batch_id_source_asset_id_fiel_key UNIQUE (batch_id, source_asset_id, field_name, channel_a, channel_b);


--
-- Name: source_reconciliation_evidence source_reconciliation_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_reconciliation_evidence
    ADD CONSTRAINT source_reconciliation_evidence_pkey PRIMARY KEY (evidence_id);


--
-- Name: source_systems source_systems_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_systems
    ADD CONSTRAINT source_systems_pkey PRIMARY KEY (source_system_id);


--
-- Name: sensor_tag_mappings tag_mapping_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tag_mappings
    ADD CONSTRAINT tag_mapping_no_overlap EXCLUDE USING gist (tag_id WITH =, measurement_definition_id WITH =, daterange(valid_from, valid_to) WITH &&);


--
-- Name: telemetry_events telemetry_events_event_id_source_instance_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_events
    ADD CONSTRAINT telemetry_events_event_id_source_instance_id_key UNIQUE (event_id, source_instance_id);


--
-- Name: telemetry_events telemetry_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_events
    ADD CONSTRAINT telemetry_events_pkey PRIMARY KEY (event_id);


--
-- Name: telemetry_events telemetry_events_source_system_id_source_event_label_source_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_events
    ADD CONSTRAINT telemetry_events_source_system_id_source_event_label_source_key UNIQUE (source_system_id, source_event_label, source_instance_id);


--
-- Name: transformations transformations_name_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transformations
    ADD CONSTRAINT transformations_name_version_key UNIQUE (name, version);


--
-- Name: transformations transformations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transformations
    ADD CONSTRAINT transformations_pkey PRIMARY KEY (transformation_id);


--
-- Name: transformations transformations_transformation_id_output_provenance_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transformations
    ADD CONSTRAINT transformations_transformation_id_output_provenance_key UNIQUE (transformation_id, output_provenance);


--
-- Name: unit_conversions unit_conversions_from_unit_id_to_unit_id_method_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unit_conversions
    ADD CONSTRAINT unit_conversions_from_unit_id_to_unit_id_method_key UNIQUE (from_unit_id, to_unit_id, method);


--
-- Name: unit_conversions unit_conversions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unit_conversions
    ADD CONSTRAINT unit_conversions_pkey PRIMARY KEY (from_unit_id, to_unit_id);


--
-- Name: units units_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_pkey PRIMARY KEY (unit_id);


--
-- Name: units units_unit_id_physical_quantity_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_unit_id_physical_quantity_key UNIQUE (unit_id, physical_quantity);


--
-- Name: work_order_transitions work_order_transitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_order_transitions
    ADD CONSTRAINT work_order_transitions_pkey PRIMARY KEY (transition_id);


--
-- Name: work_order_transitions work_order_transitions_work_order_id_sequence_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_order_transitions
    ADD CONSTRAINT work_order_transitions_work_order_id_sequence_key UNIQUE (work_order_id, sequence);


--
-- Name: work_orders work_orders_external_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_external_id_key UNIQUE (external_id);


--
-- Name: work_orders work_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_pkey PRIMARY KEY (work_order_id);


--
-- Name: anomaly_event_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX anomaly_event_idx ON public.anomaly_predictions USING btree (source_event_id);


--
-- Name: assets_geometry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assets_geometry_idx ON public.assets USING gist (geometry);


--
-- Name: assets_parent_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assets_parent_idx ON public.assets USING btree (parent_asset_id);


--
-- Name: facilities_geometry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX facilities_geometry_idx ON public.facilities USING gist (geometry);


--
-- Name: link_fictional_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX link_fictional_unique ON public.asset_observation_links USING btree (asset_id, observation_id, scenario_id) WHERE (asset_id IS NOT NULL);


--
-- Name: link_real_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX link_real_unique ON public.asset_observation_links USING btree (source_asset_id, observation_id, relationship_type) WHERE (source_asset_id IS NOT NULL);


--
-- Name: observations_event_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX observations_event_idx ON public.observations USING btree (telemetry_event_id);


--
-- Name: observations_geometry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX observations_geometry_idx ON public.observations USING gist (geometry);


--
-- Name: observations_tag_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX observations_tag_idx ON public.observations USING btree (sensor_tag_id);


--
-- Name: physical_edges_from_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX physical_edges_from_idx ON public.physical_edges USING btree (from_node_id);


--
-- Name: physical_edges_to_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX physical_edges_to_idx ON public.physical_edges USING btree (to_node_id);


--
-- Name: production_batch_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX production_batch_idx ON public.production_records USING btree (batch_id);


--
-- Name: production_period_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX production_period_idx ON public.production_records USING btree (reporting_period);


--
-- Name: quality_exceptions_asset_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quality_exceptions_asset_idx ON public.data_quality_exceptions USING btree (source_asset_id);


--
-- Name: reconciliation_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX reconciliation_status_idx ON public.reconciliation_decisions USING btree (module, verification_status);


--
-- Name: reconciliation_subject_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX reconciliation_subject_idx ON public.reconciliation_decisions USING btree (subject_type, subject_id);


--
-- Name: review_evidence_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX review_evidence_idx ON public.inspection_review_events USING btree (evidence_id);


--
-- Name: review_superseded_once; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX review_superseded_once ON public.inspection_review_events USING btree (supersedes) WHERE (supersedes IS NOT NULL);


--
-- Name: shared_events_domain_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX shared_events_domain_idx ON public.shared_events USING btree (domain, event_class);


--
-- Name: source_assets_geometry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX source_assets_geometry_idx ON public.source_assets USING gist (geometry);


--
-- Name: source_assets_parent_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX source_assets_parent_idx ON public.source_assets USING btree (parent_source_asset_id);


--
-- Name: telemetry_class_origin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX telemetry_class_origin_idx ON public.telemetry_events USING btree (source_event_label, real_or_simulated_source);


--
-- Name: approval_events approval_events_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER approval_events_append_only BEFORE DELETE OR UPDATE ON public.approval_events FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: asset_relationships asset_relationship_rule_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER asset_relationship_rule_guard BEFORE INSERT OR UPDATE ON public.asset_relationships FOR EACH ROW EXECUTE FUNCTION public.enforce_equipment_relationship();


--
-- Name: audit_events audit_events_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_events_append_only BEFORE DELETE OR UPDATE ON public.audit_events FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: detector_alarms detector_alarms_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER detector_alarms_append_only BEFORE DELETE OR UPDATE ON public.detector_alarms FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: asset_observation_links fictional_link_chain_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER fictional_link_chain_guard BEFORE INSERT OR UPDATE ON public.asset_observation_links FOR EACH ROW EXECUTE FUNCTION public.enforce_fictional_link_chain();


--
-- Name: inspection_requests inspection_request_trigger_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER inspection_request_trigger_guard BEFORE INSERT OR UPDATE ON public.inspection_requests FOR EACH ROW EXECUTE FUNCTION public.enforce_request_trigger();


--
-- Name: inspection_review_events inspection_review_chain; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER inspection_review_chain BEFORE INSERT ON public.inspection_review_events FOR EACH ROW EXECUTE FUNCTION public.enforce_review_chain();


--
-- Name: inspection_review_events inspection_review_events_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER inspection_review_events_append_only BEFORE DELETE OR UPDATE ON public.inspection_review_events FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: asset_observation_links observation_link_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER observation_link_guard BEFORE INSERT OR UPDATE ON public.asset_observation_links FOR EACH ROW EXECUTE FUNCTION public.enforce_observation_link();


--
-- Name: observations observation_sensor_source_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER observation_sensor_source_guard BEFORE INSERT OR UPDATE ON public.observations FOR EACH ROW EXECUTE FUNCTION public.enforce_observation_sensor_source();


--
-- Name: physical_edges physical_edge_rule_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER physical_edge_rule_guard BEFORE INSERT OR UPDATE ON public.physical_edges FOR EACH ROW EXECUTE FUNCTION public.enforce_physical_connection();


--
-- Name: recommendations recommendation_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER recommendation_guard BEFORE INSERT ON public.recommendations FOR EACH ROW EXECUTE FUNCTION public.enforce_recommendation();


--
-- Name: recommendations recommendations_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER recommendations_append_only BEFORE DELETE OR UPDATE ON public.recommendations FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: reconciliation_decisions reconciliation_decisions_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER reconciliation_decisions_append_only BEFORE DELETE OR UPDATE ON public.reconciliation_decisions FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: reconciliation_reviews reconciliation_reviews_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER reconciliation_reviews_append_only BEFORE DELETE OR UPDATE ON public.reconciliation_reviews FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: scenario_mappings scenario_mapping_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER scenario_mapping_guard BEFORE INSERT ON public.scenario_mappings FOR EACH ROW EXECUTE FUNCTION public.enforce_scenario_mapping();


--
-- Name: scenario_mappings scenario_mapping_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER scenario_mapping_immutable BEFORE DELETE OR UPDATE ON public.scenario_mappings FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: scenario_mappings scenario_mapping_zz_boundary; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER scenario_mapping_zz_boundary BEFORE INSERT ON public.scenario_mappings FOR EACH ROW EXECUTE FUNCTION public.enforce_domain_boundary();


--
-- Name: scenario_runs scenario_runs_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER scenario_runs_immutable BEFORE DELETE OR UPDATE ON public.scenario_runs FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: shared_events shared_event_origin_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER shared_event_origin_guard BEFORE INSERT OR UPDATE ON public.shared_events FOR EACH ROW EXECUTE FUNCTION public.enforce_benchmark_event_origin();


--
-- Name: shared_events shared_events_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER shared_events_immutable BEFORE DELETE OR UPDATE ON public.shared_events FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: work_orders work_order_creation_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER work_order_creation_guard BEFORE INSERT ON public.work_orders FOR EACH ROW EXECUTE FUNCTION public.enforce_work_order_creation();


--
-- Name: work_orders work_order_status_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER work_order_status_guard BEFORE UPDATE OF status ON public.work_orders FOR EACH ROW EXECUTE FUNCTION public.enforce_status_change();


--
-- Name: work_order_transitions work_order_transition_order; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER work_order_transition_order BEFORE INSERT ON public.work_order_transitions FOR EACH ROW EXECUTE FUNCTION public.enforce_transition_order();


--
-- Name: work_order_transitions work_order_transitions_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER work_order_transitions_append_only BEFORE DELETE OR UPDATE ON public.work_order_transitions FOR EACH ROW EXECUTE FUNCTION public.reject_change();


--
-- Name: anomaly_predictions anomaly_predictions_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_predictions
    ADD CONSTRAINT anomaly_predictions_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: anomaly_predictions anomaly_predictions_source_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_predictions
    ADD CONSTRAINT anomaly_predictions_source_event_id_fkey FOREIGN KEY (source_event_id) REFERENCES public.telemetry_events(event_id);


--
-- Name: approval_events approval_events_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_events
    ADD CONSTRAINT approval_events_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(work_order_id);


--
-- Name: asset_observation_links asset_observation_links_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_observation_links
    ADD CONSTRAINT asset_observation_links_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.assets(asset_id);


--
-- Name: asset_observation_links asset_observation_links_observation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_observation_links
    ADD CONSTRAINT asset_observation_links_observation_id_fkey FOREIGN KEY (observation_id) REFERENCES public.observations(observation_id);


--
-- Name: asset_observation_links asset_observation_links_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_observation_links
    ADD CONSTRAINT asset_observation_links_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: asset_observation_links asset_observation_links_source_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_observation_links
    ADD CONSTRAINT asset_observation_links_source_asset_id_fkey FOREIGN KEY (source_asset_id) REFERENCES public.source_assets(source_asset_id);


--
-- Name: asset_relationships asset_relationships_source_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_relationships
    ADD CONSTRAINT asset_relationships_source_asset_id_fkey FOREIGN KEY (source_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: asset_relationships asset_relationships_target_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_relationships
    ADD CONSTRAINT asset_relationships_target_asset_id_fkey FOREIGN KEY (target_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: assets assets_equipment_class_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_equipment_class_id_fkey FOREIGN KEY (equipment_class_id) REFERENCES public.equipment_classes(equipment_class_id);


--
-- Name: assets assets_facility_id_is_fictional_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_facility_id_is_fictional_fkey FOREIGN KEY (facility_id, is_fictional) REFERENCES public.facilities(facility_id, is_fictional);


--
-- Name: assets assets_parent_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_parent_asset_id_fkey FOREIGN KEY (parent_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: assets assets_transformation_id_provenance_class_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_transformation_id_provenance_class_fkey FOREIGN KEY (transformation_id, provenance_class) REFERENCES public.transformations(transformation_id, output_provenance);


--
-- Name: batch_files batch_files_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batch_files
    ADD CONSTRAINT batch_files_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.ingestion_batches(batch_id);


--
-- Name: data_quality_exceptions data_quality_exceptions_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_exceptions
    ADD CONSTRAINT data_quality_exceptions_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.ingestion_batches(batch_id);


--
-- Name: data_quality_exceptions data_quality_exceptions_source_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_exceptions
    ADD CONSTRAINT data_quality_exceptions_source_asset_id_fkey FOREIGN KEY (source_asset_id) REFERENCES public.source_assets(source_asset_id);


--
-- Name: data_quality_exceptions data_quality_exceptions_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_exceptions
    ADD CONSTRAINT data_quality_exceptions_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: reconciliation_decisions decision_review_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_decisions
    ADD CONSTRAINT decision_review_fk FOREIGN KEY (review_id) REFERENCES public.reconciliation_reviews(review_id);


--
-- Name: detector_alarms detector_alarms_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detector_alarms
    ADD CONSTRAINT detector_alarms_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: detector_alarms detector_alarms_scenario_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detector_alarms
    ADD CONSTRAINT detector_alarms_scenario_run_id_fkey FOREIGN KEY (scenario_run_id) REFERENCES public.scenario_runs(scenario_run_id);


--
-- Name: domain_boundaries domain_boundaries_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_boundaries
    ADD CONSTRAINT domain_boundaries_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: domain_compatibility_assessments domain_compatibility_assessments_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_compatibility_assessments
    ADD CONSTRAINT domain_compatibility_assessments_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: domain_compatibility_assessments domain_compatibility_assessments_target_equipment_class_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_compatibility_assessments
    ADD CONSTRAINT domain_compatibility_assessments_target_equipment_class_id_fkey FOREIGN KEY (target_equipment_class_id) REFERENCES public.equipment_classes(equipment_class_id);


--
-- Name: domain_compatibility_requirements domain_compatibility_requirement_target_equipment_class_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domain_compatibility_requirements
    ADD CONSTRAINT domain_compatibility_requirement_target_equipment_class_id_fkey FOREIGN KEY (target_equipment_class_id) REFERENCES public.equipment_classes(equipment_class_id);


--
-- Name: equipment_measurement_capabilities equipment_measurement_capabiliti_measurement_definition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment_measurement_capabilities
    ADD CONSTRAINT equipment_measurement_capabiliti_measurement_definition_id_fkey FOREIGN KEY (measurement_definition_id) REFERENCES public.measurement_definitions(measurement_definition_id);


--
-- Name: equipment_measurement_capabilities equipment_measurement_capabilities_equipment_class_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equipment_measurement_capabilities
    ADD CONSTRAINT equipment_measurement_capabilities_equipment_class_id_fkey FOREIGN KEY (equipment_class_id) REFERENCES public.equipment_classes(equipment_class_id);


--
-- Name: ingestion_batches ingestion_batches_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_batches
    ADD CONSTRAINT ingestion_batches_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: inspection_observations inspection_observations_asset_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_observations
    ADD CONSTRAINT inspection_observations_asset_candidate_id_fkey FOREIGN KEY (asset_candidate_id) REFERENCES public.assets(asset_id);


--
-- Name: inspection_observations inspection_observations_observation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_observations
    ADD CONSTRAINT inspection_observations_observation_id_fkey FOREIGN KEY (observation_id) REFERENCES public.observations(observation_id);


--
-- Name: inspection_observations inspection_observations_source_asset_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_observations
    ADD CONSTRAINT inspection_observations_source_asset_candidate_id_fkey FOREIGN KEY (source_asset_candidate_id) REFERENCES public.source_assets(source_asset_id);


--
-- Name: inspection_requests inspection_requests_affected_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_requests
    ADD CONSTRAINT inspection_requests_affected_asset_id_fkey FOREIGN KEY (affected_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: inspection_requests inspection_requests_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_requests
    ADD CONSTRAINT inspection_requests_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.assets(asset_id);


--
-- Name: inspection_requests inspection_requests_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_requests
    ADD CONSTRAINT inspection_requests_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: inspection_requests inspection_requests_scenario_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_requests
    ADD CONSTRAINT inspection_requests_scenario_run_id_fkey FOREIGN KEY (scenario_run_id) REFERENCES public.scenario_runs(scenario_run_id);


--
-- Name: inspection_requests inspection_requests_trigger_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_requests
    ADD CONSTRAINT inspection_requests_trigger_event_id_fkey FOREIGN KEY (trigger_event_id) REFERENCES public.shared_events(event_id);


--
-- Name: inspection_review_events inspection_review_events_observation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_review_events
    ADD CONSTRAINT inspection_review_events_observation_id_fkey FOREIGN KEY (observation_id) REFERENCES public.observations(observation_id);


--
-- Name: inspection_review_events inspection_review_events_supersedes_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inspection_review_events
    ADD CONSTRAINT inspection_review_events_supersedes_fkey FOREIGN KEY (supersedes) REFERENCES public.inspection_review_events(review_id);


--
-- Name: sensor_tag_mappings mapping_has_conversion; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tag_mappings
    ADD CONSTRAINT mapping_has_conversion FOREIGN KEY (original_unit_id, canonical_unit_id, conversion_method) REFERENCES public.unit_conversions(from_unit_id, to_unit_id, method);


--
-- Name: sensor_tag_mappings mapping_matches_definition; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tag_mappings
    ADD CONSTRAINT mapping_matches_definition FOREIGN KEY (measurement_definition_id, equipment_class_id, reference_type, canonical_unit_id) REFERENCES public.measurement_definitions(measurement_definition_id, equipment_class_id, reference_type, canonical_unit_id);


--
-- Name: sensor_tag_mappings mapping_matches_tag; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tag_mappings
    ADD CONSTRAINT mapping_matches_tag FOREIGN KEY (tag_id, equipment_class_id, reference_type, original_unit_id) REFERENCES public.sensor_tags(tag_id, equipment_class_id, pressure_reference_type, unit_id);


--
-- Name: measurement_definitions measurement_definitions_canonical_unit_id_physical_quantit_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.measurement_definitions
    ADD CONSTRAINT measurement_definitions_canonical_unit_id_physical_quantit_fkey FOREIGN KEY (canonical_unit_id, physical_quantity) REFERENCES public.units(unit_id, physical_quantity);


--
-- Name: measurement_definitions measurement_definitions_equipment_class_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.measurement_definitions
    ADD CONSTRAINT measurement_definitions_equipment_class_id_fkey FOREIGN KEY (equipment_class_id) REFERENCES public.equipment_classes(equipment_class_id);


--
-- Name: observations observation_run_scenario_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observation_run_scenario_fk FOREIGN KEY (scenario_run_id, scenario_id) REFERENCES public.scenario_runs(scenario_run_id, scenario_id);


--
-- Name: observations observation_scenario_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observation_scenario_fk FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: observations observations_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.ingestion_batches(batch_id);


--
-- Name: observations observations_replayed_from_observation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_replayed_from_observation_id_fkey FOREIGN KEY (replayed_from_observation_id) REFERENCES public.observations(observation_id);


--
-- Name: observations observations_scenario_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_scenario_run_id_fkey FOREIGN KEY (scenario_run_id) REFERENCES public.scenario_runs(scenario_run_id);


--
-- Name: observations observations_sensor_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_sensor_tag_id_fkey FOREIGN KEY (sensor_tag_id) REFERENCES public.sensor_tags(tag_id);


--
-- Name: observations observations_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: observations observations_telemetry_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_telemetry_event_id_fkey FOREIGN KEY (telemetry_event_id) REFERENCES public.telemetry_events(event_id);


--
-- Name: observations observations_transformation_id_provenance_class_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_transformation_id_provenance_class_fkey FOREIGN KEY (transformation_id, provenance_class) REFERENCES public.transformations(transformation_id, output_provenance);


--
-- Name: observations observations_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(unit_id);


--
-- Name: physical_edges physical_edges_element_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_edges
    ADD CONSTRAINT physical_edges_element_asset_id_fkey FOREIGN KEY (element_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: physical_edges physical_edges_from_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_edges
    ADD CONSTRAINT physical_edges_from_node_id_fkey FOREIGN KEY (from_node_id) REFERENCES public.physical_nodes(node_id);


--
-- Name: physical_edges physical_edges_to_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_edges
    ADD CONSTRAINT physical_edges_to_node_id_fkey FOREIGN KEY (to_node_id) REFERENCES public.physical_nodes(node_id);


--
-- Name: physical_edges physical_edges_valve_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_edges
    ADD CONSTRAINT physical_edges_valve_asset_id_fkey FOREIGN KEY (valve_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: physical_nodes physical_nodes_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_nodes
    ADD CONSTRAINT physical_nodes_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.assets(asset_id);


--
-- Name: physical_nodes physical_nodes_facility_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.physical_nodes
    ADD CONSTRAINT physical_nodes_facility_id_fkey FOREIGN KEY (facility_id) REFERENCES public.facilities(facility_id);


--
-- Name: production_records production_records_batch_id_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_records
    ADD CONSTRAINT production_records_batch_id_source_system_id_fkey FOREIGN KEY (batch_id, source_system_id) REFERENCES public.ingestion_batches(batch_id, source_system_id);


--
-- Name: production_records production_records_reporting_entity_id_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_records
    ADD CONSTRAINT production_records_reporting_entity_id_source_system_id_fkey FOREIGN KEY (reporting_entity_id, source_system_id) REFERENCES public.source_assets(source_asset_id, source_system_id);


--
-- Name: production_records production_records_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_records
    ADD CONSTRAINT production_records_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: production_records production_records_source_system_id_product_kind_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_records
    ADD CONSTRAINT production_records_source_system_id_product_kind_unit_id_fkey FOREIGN KEY (source_system_id, product_kind, unit_id) REFERENCES public.production_unit_rules(source_system_id, product_kind, unit_id);


--
-- Name: production_records production_records_transformation_id_provenance_class_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_records
    ADD CONSTRAINT production_records_transformation_id_provenance_class_fkey FOREIGN KEY (transformation_id, provenance_class) REFERENCES public.transformations(transformation_id, output_provenance);


--
-- Name: production_unit_rules production_unit_rules_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_unit_rules
    ADD CONSTRAINT production_unit_rules_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: production_unit_rules production_unit_rules_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.production_unit_rules
    ADD CONSTRAINT production_unit_rules_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(unit_id);


--
-- Name: recommendations recommendations_alarm_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendations
    ADD CONSTRAINT recommendations_alarm_id_fkey FOREIGN KEY (alarm_id) REFERENCES public.detector_alarms(alarm_id);


--
-- Name: recommendations recommendations_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendations
    ADD CONSTRAINT recommendations_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: recommendations recommendations_scenario_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recommendations
    ADD CONSTRAINT recommendations_scenario_run_id_fkey FOREIGN KEY (scenario_run_id) REFERENCES public.scenario_runs(scenario_run_id);


--
-- Name: reconciliation_decisions reconciliation_decisions_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_decisions
    ADD CONSTRAINT reconciliation_decisions_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.ingestion_batches(batch_id);


--
-- Name: reconciliation_decisions reconciliation_decisions_supersedes_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_decisions
    ADD CONSTRAINT reconciliation_decisions_supersedes_decision_id_fkey FOREIGN KEY (supersedes_decision_id) REFERENCES public.reconciliation_decisions(decision_id);


--
-- Name: reconciliation_reviews reconciliation_reviews_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reconciliation_reviews
    ADD CONSTRAINT reconciliation_reviews_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.reconciliation_decisions(decision_id);


--
-- Name: scenario_mappings scenario_mappings_compatibility_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_mappings
    ADD CONSTRAINT scenario_mappings_compatibility_assessment_id_fkey FOREIGN KEY (compatibility_assessment_id) REFERENCES public.domain_compatibility_assessments(assessment_id);


--
-- Name: scenario_mappings scenario_mappings_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_mappings
    ADD CONSTRAINT scenario_mappings_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: scenario_mappings scenario_mappings_target_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_mappings
    ADD CONSTRAINT scenario_mappings_target_asset_id_fkey FOREIGN KEY (target_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: scenario_mappings scenario_mappings_telemetry_event_id_original_source_insta_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_mappings
    ADD CONSTRAINT scenario_mappings_telemetry_event_id_original_source_insta_fkey FOREIGN KEY (telemetry_event_id, original_source_instance_id) REFERENCES public.telemetry_events(event_id, source_instance_id);


--
-- Name: scenario_runs scenario_runs_affected_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_runs
    ADD CONSTRAINT scenario_runs_affected_asset_id_fkey FOREIGN KEY (affected_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: scenario_runs scenario_runs_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_runs
    ADD CONSTRAINT scenario_runs_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: scenario_runs scenario_runs_target_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_runs
    ADD CONSTRAINT scenario_runs_target_asset_id_fkey FOREIGN KEY (target_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: scenario_runs scenario_runs_transformation_id_provenance_class_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_runs
    ADD CONSTRAINT scenario_runs_transformation_id_provenance_class_fkey FOREIGN KEY (transformation_id, provenance_class) REFERENCES public.transformations(transformation_id, output_provenance);


--
-- Name: scenarios scenarios_target_facility_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenarios
    ADD CONSTRAINT scenarios_target_facility_id_fkey FOREIGN KEY (target_facility_id) REFERENCES public.facilities(facility_id);


--
-- Name: sensor_tag_mappings sensor_tag_mappings_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tag_mappings
    ADD CONSTRAINT sensor_tag_mappings_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: sensor_tags sensor_tags_equipment_class_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tags
    ADD CONSTRAINT sensor_tags_equipment_class_id_fkey FOREIGN KEY (equipment_class_id) REFERENCES public.equipment_classes(equipment_class_id);


--
-- Name: sensor_tags sensor_tags_fictional_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tags
    ADD CONSTRAINT sensor_tags_fictional_asset_id_fkey FOREIGN KEY (fictional_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: sensor_tags sensor_tags_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tags
    ADD CONSTRAINT sensor_tags_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: sensor_tags sensor_tags_unit_id_physical_quantity_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_tags
    ADD CONSTRAINT sensor_tags_unit_id_physical_quantity_fkey FOREIGN KEY (unit_id, physical_quantity) REFERENCES public.units(unit_id, physical_quantity);


--
-- Name: shared_events shared_events_affected_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_events
    ADD CONSTRAINT shared_events_affected_asset_id_fkey FOREIGN KEY (affected_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: shared_events shared_events_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_events
    ADD CONSTRAINT shared_events_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- Name: shared_events shared_events_scenario_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_events
    ADD CONSTRAINT shared_events_scenario_run_id_fkey FOREIGN KEY (scenario_run_id) REFERENCES public.scenario_runs(scenario_run_id);


--
-- Name: shared_events shared_events_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_events
    ADD CONSTRAINT shared_events_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: shared_events shared_events_target_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_events
    ADD CONSTRAINT shared_events_target_asset_id_fkey FOREIGN KEY (target_asset_id) REFERENCES public.assets(asset_id);


--
-- Name: shared_events shared_events_telemetry_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_events
    ADD CONSTRAINT shared_events_telemetry_event_id_fkey FOREIGN KEY (telemetry_event_id) REFERENCES public.telemetry_events(event_id);


--
-- Name: shared_events shared_events_transformation_id_provenance_class_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_events
    ADD CONSTRAINT shared_events_transformation_id_provenance_class_fkey FOREIGN KEY (transformation_id, provenance_class) REFERENCES public.transformations(transformation_id, output_provenance);


--
-- Name: source_asset_history source_asset_history_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_asset_history
    ADD CONSTRAINT source_asset_history_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.ingestion_batches(batch_id);


--
-- Name: source_asset_history source_asset_history_source_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_asset_history
    ADD CONSTRAINT source_asset_history_source_asset_id_fkey FOREIGN KEY (source_asset_id) REFERENCES public.source_assets(source_asset_id);


--
-- Name: source_asset_history source_asset_history_transformation_id_provenance_class_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_asset_history
    ADD CONSTRAINT source_asset_history_transformation_id_provenance_class_fkey FOREIGN KEY (transformation_id, provenance_class) REFERENCES public.transformations(transformation_id, output_provenance);


--
-- Name: source_assets source_assets_batch_id_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_assets
    ADD CONSTRAINT source_assets_batch_id_source_system_id_fkey FOREIGN KEY (batch_id, source_system_id) REFERENCES public.ingestion_batches(batch_id, source_system_id);


--
-- Name: source_assets source_assets_equipment_class_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_assets
    ADD CONSTRAINT source_assets_equipment_class_id_fkey FOREIGN KEY (equipment_class_id) REFERENCES public.equipment_classes(equipment_class_id);


--
-- Name: source_assets source_assets_parent_source_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_assets
    ADD CONSTRAINT source_assets_parent_source_asset_id_fkey FOREIGN KEY (parent_source_asset_id) REFERENCES public.source_assets(source_asset_id);


--
-- Name: source_assets source_assets_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_assets
    ADD CONSTRAINT source_assets_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: source_assets source_assets_transformation_id_provenance_class_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_assets
    ADD CONSTRAINT source_assets_transformation_id_provenance_class_fkey FOREIGN KEY (transformation_id, provenance_class) REFERENCES public.transformations(transformation_id, output_provenance);


--
-- Name: source_event_classes source_event_classes_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_event_classes
    ADD CONSTRAINT source_event_classes_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: source_identifiers source_identifiers_canonical_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_identifiers
    ADD CONSTRAINT source_identifiers_canonical_asset_id_fkey FOREIGN KEY (canonical_asset_id) REFERENCES public.source_assets(source_asset_id);


--
-- Name: source_identifiers source_identifiers_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_identifiers
    ADD CONSTRAINT source_identifiers_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: source_reconciliation_evidence source_reconciliation_evidence_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_reconciliation_evidence
    ADD CONSTRAINT source_reconciliation_evidence_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.ingestion_batches(batch_id);


--
-- Name: source_reconciliation_evidence source_reconciliation_evidence_source_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_reconciliation_evidence
    ADD CONSTRAINT source_reconciliation_evidence_source_asset_id_fkey FOREIGN KEY (source_asset_id) REFERENCES public.source_assets(source_asset_id);


--
-- Name: telemetry_events telemetry_events_batch_id_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_events
    ADD CONSTRAINT telemetry_events_batch_id_source_system_id_fkey FOREIGN KEY (batch_id, source_system_id) REFERENCES public.ingestion_batches(batch_id, source_system_id);


--
-- Name: telemetry_events telemetry_events_source_asset_id_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_events
    ADD CONSTRAINT telemetry_events_source_asset_id_source_system_id_fkey FOREIGN KEY (source_asset_id, source_system_id) REFERENCES public.source_assets(source_asset_id, source_system_id);


--
-- Name: telemetry_events telemetry_events_source_system_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_events
    ADD CONSTRAINT telemetry_events_source_system_id_fkey FOREIGN KEY (source_system_id) REFERENCES public.source_systems(source_system_id);


--
-- Name: telemetry_events telemetry_events_source_system_id_source_event_label_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_events
    ADD CONSTRAINT telemetry_events_source_system_id_source_event_label_fkey FOREIGN KEY (source_system_id, source_event_label) REFERENCES public.source_event_classes(source_system_id, event_label);


--
-- Name: telemetry_events telemetry_events_transformation_id_provenance_class_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_events
    ADD CONSTRAINT telemetry_events_transformation_id_provenance_class_fkey FOREIGN KEY (transformation_id, provenance_class) REFERENCES public.transformations(transformation_id, output_provenance);


--
-- Name: unit_conversions unit_conversions_from_unit_id_physical_quantity_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unit_conversions
    ADD CONSTRAINT unit_conversions_from_unit_id_physical_quantity_fkey FOREIGN KEY (from_unit_id, physical_quantity) REFERENCES public.units(unit_id, physical_quantity);


--
-- Name: unit_conversions unit_conversions_to_unit_id_physical_quantity_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unit_conversions
    ADD CONSTRAINT unit_conversions_to_unit_id_physical_quantity_fkey FOREIGN KEY (to_unit_id, physical_quantity) REFERENCES public.units(unit_id, physical_quantity);


--
-- Name: work_order_transitions work_order_transitions_work_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_order_transitions
    ADD CONSTRAINT work_order_transitions_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES public.work_orders(work_order_id);


--
-- Name: work_orders work_orders_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.assets(asset_id);


--
-- Name: work_orders work_orders_recommendation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_recommendation_id_fkey FOREIGN KEY (recommendation_id) REFERENCES public.recommendations(recommendation_id);


--
-- Name: work_orders work_orders_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_orders
    ADD CONSTRAINT work_orders_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenarios(scenario_id);


--
-- PostgreSQL database dump complete
--

