"""Attempts to break the provenance and semantic boundaries. Every statement here must be refused by the database."""

from __future__ import annotations

import psycopg
import pytest

pytestmark = pytest.mark.db
INCOMPATIBLE_EVENT = "3w-aether:EVENT_CLASS:SPURIOUS_CLOSURE_OF_DHSV:v1"
UNKNOWN_EVENT = "3w-aether:EVENT_CLASS:SCALING_IN_PCK:v1"
REAL_EVENT = "petrobras_3w:2:WELL-00002_20131104004101"
REAL_INSTANCE = "WELL-00002_20131104004101"
OCD_WELL = "nm_ocd:well:30-015-90001"
W3_WELL = "petrobras_3w:well:WELL-00002"


def refused(conn, sql, params=None, error=psycopg.errors.IntegrityError):
    """Assert the statement fails, and roll back only that statement."""
    with pytest.raises(error):
        with conn.transaction():
            conn.execute(sql, params)


def scenario(conn):
    conn.execute(
        """INSERT INTO scenarios (scenario_id, scenario_name, scenario_description, target_facility_id, scenario_version, random_seed)
           VALUES ('S1', 'test', 'test scenario', 'AETHER-FIELD', 1, 7) ON CONFLICT DO NOTHING"""
    )


def observation_id(conn, system="petrobras_3w"):
    return conn.execute(
        "SELECT observation_id FROM observations WHERE source_system_id=%s LIMIT 1", (system,)
    ).fetchone()[0]


# Fictional and real identities


def test_aether_cannot_be_marked_real(db):
    refused(db, "UPDATE facilities SET is_fictional = false WHERE facility_id = 'AETHER-FIELD'")


def test_fictional_asset_cannot_be_marked_real(db):
    refused(db, "UPDATE assets SET is_fictional = false WHERE asset_id = 'A-01'")


def test_fictional_asset_cannot_claim_observed(db):
    refused(db, "UPDATE assets SET provenance_class = 'OBSERVED' WHERE asset_id = 'A-01'")


def test_real_source_asset_cannot_claim_synthetic(db):
    refused(
        db,
        "UPDATE source_assets SET provenance_class = 'SYNTHETIC' WHERE source_asset_id = %s",
        (OCD_WELL,),
    )


def test_real_identifier_cannot_resolve_to_a_fictional_asset(db):
    refused(
        db,
        """INSERT INTO source_identifiers (source_system_id, canonical_asset_id, external_identifier, identifier_type, verification_status)
           VALUES ('nm_ocd', 'A-01', 'X', 'API_NUMBER', 'VERIFIED')""",
    )


def test_verified_identifier_needs_an_asset(db):
    refused(
        db,
        """INSERT INTO source_identifiers (source_system_id, external_identifier, identifier_type, verification_status)
           VALUES ('nm_ocd', 'X', 'API_NUMBER', 'VERIFIED')""",
    )


def test_fictional_relationship_cannot_be_observed(db):
    refused(
        db,
        """INSERT INTO asset_relationships (source_asset_id, target_asset_id, relationship_type, evidence_type, provenance_class)
           VALUES ('A-01', 'A-02', 'CONNECTED', 'NONE', 'OBSERVED')""",
    )


def test_work_order_cannot_target_a_real_well(db):
    scenario(db)
    refused(
        db,
        """INSERT INTO work_orders (scenario_id, asset_id, recommended_action, severity, priority, status, evidence_reference)
           VALUES ('S1', %s, 'inspect', 'LOW', 1, 'RECOMMENDED', 'e')""",
        (OCD_WELL,),
    )


# Provenance tied to transformations


def test_row_cannot_claim_a_class_its_transformation_does_not_produce(db):
    refused(
        db,
        "UPDATE telemetry_events SET transformation_id = '3w.generated_instance.to_event@1' WHERE event_id = %s",
        (REAL_EVENT,),
    )


def test_observed_output_cannot_come_from_a_value_altering_process(db):
    refused(
        db,
        """INSERT INTO transformations VALUES ('bad@1','bad',1,'x','x',ARRAY['OBSERVED']::provenance_class[],'OBSERVED',true)""",
    )


def test_observed_output_cannot_come_from_synthetic_input(db):
    refused(
        db,
        """INSERT INTO transformations VALUES ('bad@1','bad',1,'x','x',ARRAY['SYNTHETIC']::provenance_class[],'OBSERVED',false)""",
    )


def test_derived_output_cannot_launder_synthetic_input(db):
    refused(
        db,
        """INSERT INTO transformations VALUES ('bad@1','bad',1,'x','x',ARRAY['OBSERVED','SYNTHETIC']::provenance_class[],'DERIVED',true)""",
    )


def test_unknown_provenance_class_is_rejected(db):
    refused(db, "SELECT 'MEASURED'::provenance_class", error=psycopg.errors.DataError)


def test_generated_instance_cannot_become_observed(db):
    refused(
        db,
        "UPDATE telemetry_events SET provenance_class='OBSERVED', transformation_id='3w.real_instance.to_event@1' WHERE real_or_simulated_source='SIMULATED'",
    )


def test_generated_instance_cannot_be_given_a_source_well(db):
    refused(
        db,
        "UPDATE telemetry_events SET source_asset_id=%s WHERE real_or_simulated_source='SIMULATED'",
        (W3_WELL,),
    )


def test_real_instance_cannot_lose_its_source_well(db):
    refused(db, "UPDATE telemetry_events SET source_asset_id=NULL WHERE event_id=%s", (REAL_EVENT,))


def test_replayed_observation_must_keep_its_origin_and_scenario(db):
    db.execute(
        """INSERT INTO transformations VALUES ('replay@1','replay',1,'x','x',ARRAY['OBSERVED']::provenance_class[],'REPLAYED',false)"""
    )
    refused(
        db,
        """INSERT INTO observations (source_system_id, source_record_id, observation_type, metric_name, quality_flag,
             provenance_class, original_record_uri, transformation_id)
           VALUES ('petrobras_3w', 'r1', 'TELEMETRY_SERIES', 'x', 'COMPLETE', 'REPLAYED', 'u', 'replay@1')""",
    )


# Semantics


def test_offshore_tag_cannot_map_to_onshore_wellhead_pressure(db):
    for class_id in ("OFFSHORE_SUBSEA_WELL", "AETHER_ONSHORE_GAS_WELL"):
        for reference in ("UNKNOWN", "GAUGE"):
            refused(
                db,
                """INSERT INTO sensor_tag_mappings (tag_id, measurement_definition_id, equipment_class_id, reference_type,
                     source_system_id, original_unit_id, canonical_unit_id, conversion_method, data_quality_state, mapping_status, rationale)
                   VALUES ('petrobras_3w:PT-P', 'aether_well.tubing_head_pressure', %s, %s, 'petrobras_3w', 'Pa', 'Pa', 'IDENTITY', 'NOT_ASSESSED', 'UNVERIFIED', 'x')""",
                (class_id, reference),
            )


def test_unknown_reference_cannot_be_changed_to_gauge_in_a_mapping(db):
    refused(
        db,
        "UPDATE sensor_tag_mappings SET reference_type='GAUGE' WHERE tag_id='petrobras_3w:PT-P'",
    )


def test_pressure_tag_needs_a_reference_type(db):
    refused(
        db,
        """INSERT INTO sensor_tags (tag_id, source_system_id, native_tag_name, equipment_position, equipment_class_id,
             physical_quantity, unit_id, pressure_reference_type, mapping_status, source_description)
           VALUES ('t','petrobras_3w','t','p','OFFSHORE_SUBSEA_WELL','pressure','Pa','NOT_APPLICABLE','UNVERIFIED','d')""",
    )


def test_unit_must_measure_the_stated_quantity(db):
    refused(
        db,
        """INSERT INTO sensor_tags (tag_id, source_system_id, native_tag_name, equipment_position, equipment_class_id,
             physical_quantity, unit_id, pressure_reference_type, mapping_status, source_description)
           VALUES ('t','petrobras_3w','t','p','OFFSHORE_SUBSEA_WELL','temperature','Pa','NOT_APPLICABLE','UNVERIFIED','d')""",
    )


def test_conversion_cannot_cross_physical_quantities(db):
    refused(
        db,
        "INSERT INTO unit_conversions VALUES ('Pa','degC','pressure',1,0,'BAD')",
    )


def test_gas_volume_cannot_be_stored_in_barrels(db):
    refused(db, "UPDATE production_records SET unit_id='BBL_60F' WHERE product_kind='G'")


def test_production_cannot_use_an_unverified_product_kind(db):
    refused(db, "UPDATE production_records SET product_kind='Z' WHERE product_kind='G'")


def test_reporting_period_must_be_a_month(db):
    refused(db, "UPDATE production_records SET reporting_period='2026-06-30'")


def test_reporting_grain_is_constrained(db):
    refused(db, "UPDATE production_records SET reporting_grain='PAD'")


def test_negative_volume_is_refused(db):
    refused(db, "UPDATE production_records SET reported_volume=-1")


def test_usable_status_requires_a_geometry(db):
    refused(
        db,
        "UPDATE source_assets SET spatial_status='USABLE' WHERE external_identifier='30-015-90005'",
    )


def test_quarantined_well_cannot_keep_a_geometry(db):
    refused(
        db,
        """UPDATE source_assets SET geometry=ST_SetSRID(ST_MakePoint(-104.08,33.3),4269)
           WHERE external_identifier='30-015-90005'""",
    )


def test_overlapping_history_is_refused(db):
    asset = OCD_WELL
    row = db.execute(
        "SELECT batch_id, transformation_id FROM source_asset_history WHERE source_asset_id=%s LIMIT 1",
        (asset,),
    ).fetchone()
    refused(
        db,
        """INSERT INTO source_asset_history (source_asset_id, valid_from, provenance_class, batch_id, transformation_id, source_record_key)
           VALUES (%s, '2021-01-01', 'OBSERVED', %s, %s, 'k')""",
        (asset, row[0], row[1]),
    )


def test_batch_counts_must_reconcile(db):
    refused(db, "UPDATE ingestion_batches SET rejected_count = rejected_count + 1")


# Scenario boundary


def insert_mapping(conn, assessment, conditions=None, provenance="REPLAYED", asset="A-01"):
    conn.execute(
        """INSERT INTO scenario_mappings (scenario_id, target_asset_id, telemetry_event_id, original_source_instance_id,
             transformation_config, compatibility_assessment_id, conditions_satisfied, mapping_provenance)
           VALUES ('S1', %s, %s, %s, '{}', %s, %s, %s)""",
        (asset, REAL_EVENT, REAL_INSTANCE, assessment, conditions, provenance),
    )


def test_incompatible_event_cannot_be_mapped_to_aether(db):
    scenario(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="INCOMPATIBLE"):
        with db.transaction():
            insert_mapping(db, INCOMPATIBLE_EVENT)


def test_assessment_for_another_event_class_cannot_be_borrowed(db):
    scenario(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="does not cover event class"):
        with db.transaction():
            insert_mapping(db, UNKNOWN_EVENT)


def test_variable_assessment_cannot_authorize_an_event_mapping(db):
    scenario(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            insert_mapping(db, "3w-aether:VARIABLE:ABER-CKP:v1")


def conditional_case(db):
    """An event class with a conditional assessment, attached to a real instance for testing."""
    scenario(db)
    # These tests exercise the assessment layer, so they lift the newer boundary inside this
    # always-rolled-back transaction. tests/provenance/test_reconciliation_invariants.py covers it.
    db.execute(
        "UPDATE domain_boundaries SET is_allowed = true WHERE source_system_id = 'petrobras_3w'"
    )
    db.execute(
        "UPDATE telemetry_events SET source_event_label=6, source_event_class='QUICK_RESTRICTION_IN_PCK' WHERE event_id=%s",
        (REAL_EVENT,),
    )
    return "3w-aether:EVENT_CLASS:QUICK_RESTRICTION_IN_PCK:v1"


def test_conditional_event_needs_evidence_for_every_condition(db):
    assessment = conditional_case(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="every condition"):
        with db.transaction():
            insert_mapping(db, assessment, '["only one"]')


def test_conditional_mapping_with_evidence_succeeds_and_keeps_source_identity(db):
    assessment = conditional_case(db)
    insert_mapping(db, assessment, '["a", "b", "c", "d"]')
    row = db.execute(
        """SELECT m.original_source_instance_id, m.mapping_provenance, e.source_asset_id
           FROM scenario_mappings m JOIN telemetry_events e ON e.event_id = m.telemetry_event_id"""
    ).fetchone()
    assert row == (REAL_INSTANCE, "REPLAYED", W3_WELL)


def test_scenario_mapping_cannot_be_observed(db):
    assessment = conditional_case(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            insert_mapping(db, assessment, '["a", "b", "c", "d"]', provenance="OBSERVED")


def test_scenario_mapping_must_point_at_a_fictional_asset(db):
    assessment = conditional_case(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="target class"):
        with db.transaction():
            insert_mapping(db, assessment, '["a", "b", "c", "d"]', asset=OCD_WELL)


def test_scenario_mapping_cannot_overwrite_source_identity(db):
    assessment = conditional_case(db)
    insert_mapping(db, assessment, '["a", "b", "c", "d"]')
    refused(
        db,
        "UPDATE scenario_mappings SET original_source_instance_id='WELL-99999_20000101000000'",
        error=psycopg.errors.RestrictViolation,
    )
    refused(db, "DELETE FROM scenario_mappings", error=psycopg.errors.RestrictViolation)


def test_mapping_cannot_misstate_the_original_instance(db):
    assessment = conditional_case(db)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db.transaction():
            db.execute(
                """INSERT INTO scenario_mappings (scenario_id, target_asset_id, telemetry_event_id, original_source_instance_id,
                     transformation_config, compatibility_assessment_id, conditions_satisfied, mapping_provenance)
                   VALUES ('S1','A-01',%s,'WELL-99999_20000101000000','{}',%s,'["a","b","c","d"]','REPLAYED')""",
                (REAL_EVENT, assessment),
            )


# Observation links


def link(conn, **values):
    columns = {
        "verification_status": "UNVERIFIED",
        "method_version": "t",
        "provenance_class": "INFERRED",
        **values,
    }
    names = ", ".join(columns)
    marks = ", ".join(["%s"] * len(columns))
    conn.execute(
        f"INSERT INTO asset_observation_links ({names}) VALUES ({marks})", tuple(columns.values())
    )


def test_fictional_asset_cannot_be_measured_at(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            link(
                db,
                asset_id="A-01",
                observation_id=observation_id(db),
                relationship_type="MEASURED_AT",
            )


def test_experimental_link_requires_a_scenario(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            link(
                db,
                asset_id="A-01",
                observation_id=observation_id(db),
                relationship_type="EXPERIMENTAL_SCENARIO_LINK",
            )


def test_experimental_link_cannot_be_verified_or_observed(db):
    scenario(db)
    for overrides in ({"verification_status": "VERIFIED"}, {"provenance_class": "OBSERVED"}):
        with pytest.raises(psycopg.errors.CheckViolation):
            with db.transaction():
                link(
                    db,
                    asset_id="A-01",
                    scenario_id="S1",
                    observation_id=observation_id(db),
                    relationship_type="EXPERIMENTAL_SCENARIO_LINK",
                    **overrides,
                )


def test_3w_observation_cannot_be_measured_at_a_new_mexico_well(db):
    with pytest.raises(psycopg.errors.CheckViolation, match="one source system"):
        with db.transaction():
            link(
                db,
                source_asset_id=OCD_WELL,
                observation_id=observation_id(db),
                relationship_type="MEASURED_AT",
            )


def test_link_cannot_target_both_real_and_fictional(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            link(
                db,
                source_asset_id=W3_WELL,
                asset_id="A-01",
                observation_id=observation_id(db),
                relationship_type="ASSOCIATED_WITH",
            )


def test_confidence_without_evidence_is_refused(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            link(
                db,
                source_asset_id=W3_WELL,
                observation_id=observation_id(db),
                relationship_type="ASSOCIATED_WITH",
                confidence=0.9,
            )


def test_attribution_requires_verified_evidence(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            link(
                db,
                source_asset_id=W3_WELL,
                observation_id=observation_id(db),
                relationship_type="SOURCE_ATTRIBUTED_TO",
            )


def test_emission_proximity_cannot_be_promoted_to_attribution(db):
    link(
        db,
        source_asset_id=W3_WELL,
        observation_id=observation_id(db),
        relationship_type="EMISSION_NEAR",
    )
    refused(
        db,
        """UPDATE asset_observation_links SET relationship_type='SOURCE_ATTRIBUTED_TO', verification_status='VERIFIED', evidence_reference='x'
           WHERE relationship_type='EMISSION_NEAR'""",
        error=psycopg.errors.RestrictViolation,
    )


def test_emission_proximity_cannot_be_verified(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            link(
                db,
                source_asset_id=W3_WELL,
                observation_id=observation_id(db),
                relationship_type="EMISSION_NEAR",
                verification_status="VERIFIED",
            )


# Audit


def test_audit_events_are_append_only(db):
    db.execute(
        "INSERT INTO audit_events (actor_id, operation, target_id, correlation_id) VALUES ('a','o','t','c')"
    )
    refused(db, "UPDATE audit_events SET actor_id='b'", error=psycopg.errors.RestrictViolation)
    refused(db, "DELETE FROM audit_events", error=psycopg.errors.RestrictViolation)


def test_work_order_requires_evidence(db):
    scenario(db)
    refused(
        db,
        """INSERT INTO work_orders (scenario_id, asset_id, recommended_action, severity, priority, status, evidence_reference)
           VALUES ('S1', 'A-01', 'inspect', 'LOW', 1, 'RECOMMENDED', NULL)""",
    )
