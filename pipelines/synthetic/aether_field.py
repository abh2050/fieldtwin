"""Run every field scenario, refuse any that break a check, write outputs, and record lineage."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import psycopg

from packages.reconciliation.provenance import require_simulated_is_synthetic
from packages.reconciliation.review import store_decisions
from packages.reconciliation.scenario import assignment_decision, require_scenario_source
from packages.repositories.database import REPO_ROOT, connect
from packages.scenario_engine.field_events import field_events
from packages.scenario_engine.field_invariants import FieldCheck, require_field_run
from packages.scenario_engine.field_simulation import FieldRun, default_setup, simulate_by_id
from pipelines.normalize.petrobras_3w_events import insert_events

OUTPUT_DIR = Path("data") / "gold" / "scenarios" / "aether_field"
RUN_TRANSFORMATION = "aether.field_simulator.to_run@1"
SERIES_TRANSFORMATION = "aether.field_simulator.to_series@1"


def execute_all() -> dict[str, tuple[FieldRun, list[FieldCheck]]]:
    results = {}
    for scenario in default_setup()[3].scenarios:
        run = simulate_by_id(scenario.scenario_id)
        for provenance in run.telemetry["provenance_class"].unique():
            require_simulated_is_synthetic(provenance)
        results[scenario.scenario_id] = (run, require_field_run(run))
    return results


def write_outputs(
    root: Path, results: dict[str, tuple[FieldRun, list[FieldCheck]]]
) -> dict[str, str]:
    folder = root / OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    uris = {}
    for scenario_id, (run, _) in results.items():
        run.telemetry.to_parquet(folder / f"{scenario_id}_telemetry.parquet", index=False)
        run.truth.to_parquet(folder / f"{scenario_id}_truth.parquet", index=False)
        uris[scenario_id] = (OUTPUT_DIR / f"{scenario_id}_telemetry.parquet").as_posix()
    return uris


def persist_run(
    conn: psycopg.Connection, run: FieldRun, checks: list[FieldCheck], uri: str, algorithm: str
) -> dict[str, int]:
    """Record one run. Each series gets its sensor, asset, scenario, run, and parameter set."""
    config, _, _, catalog, sensors = default_setup()
    scenario = run.scenario
    if conn.execute(
        "SELECT 1 FROM scenario_runs WHERE scenario_run_id = %s", (run.run_id,)
    ).fetchone():
        return {"already_recorded": 1}
    domain = conn.execute(
        "SELECT c.domain FROM assets a JOIN equipment_classes c USING (equipment_class_id) WHERE a.asset_id = %s",
        (scenario.target_asset_id,),
    ).fetchone()
    require_scenario_source("aether_synthetic", domain[0] if domain else "")
    counts = {"runs": 1, "series": 0, "links": 0}
    with conn.transaction():
        conn.execute(
            """INSERT INTO scenarios (scenario_id, scenario_name, scenario_description, target_facility_id, scenario_version, random_seed)
               VALUES (%s, %s, %s, 'AETHER-FIELD', %s, %s)""",
            (scenario.scenario_id, scenario.name, scenario.description, scenario.version, run.seed),
        )
        parameters = {
            "network": config.model_dump(mode="json", by_alias=True),
            "simulation": catalog.simulation.model_dump(mode="json"),
            "scenario": scenario.model_dump(mode="json"),
        }
        conn.execute(
            """INSERT INTO scenario_runs (scenario_run_id, scenario_id, case_name, target_asset_id, affected_asset_id,
                 simulator_name, simulator_version, config_sha256, output_sha256, output_uri, random_seed, sample_count,
                 sampling_interval_s, fault_onset_offset_s, parameters, invariants, provenance_class, transformation_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'SYNTHETIC', %s)""",
            (
                run.run_id, scenario.scenario_id, scenario.case_name, scenario.target_asset_id, scenario.affected_asset_id,
                run.simulator_name, run.simulator_version, run.parameter_set_sha256, run.canonical_sha256(), uri, run.seed,
                len(run.truth), catalog.simulation.interval_s,
                scenario.first_onset_s if scenario.case_name == "fault" else None,
                json.dumps(parameters), json.dumps([asdict(c) for c in checks]), RUN_TRANSFORMATION,
            ),
        )  # fmt: skip
        by_tag = run.telemetry.groupby("tag")
        for sensor in sensors:
            rows = by_tag.get_group(sensor.tag)
            nulls = int(rows["value"].isna().sum())
            row = conn.execute(
                """INSERT INTO observations (source_system_id, source_record_id, observation_type, metric_name, unit_id,
                     quality_flag, provenance_class, original_record_uri, sensor_tag_id, value_count, null_count,
                     scenario_id, scenario_run_id, transformation_id)
                   VALUES ('aether_synthetic', %s, 'TELEMETRY_SERIES', %s, %s, %s, 'SYNTHETIC', %s, %s, %s, %s, %s, %s, %s)
                   RETURNING observation_id""",
                (
                    f"{run.run_id}#{sensor.tag}", sensor.tag, sensor.unit, "PARTIAL" if nulls else "COMPLETE",
                    f"{uri}#tag={sensor.tag}", f"aether_synthetic:{sensor.tag}", len(rows) - nulls, nulls,
                    scenario.scenario_id, run.run_id, SERIES_TRANSFORMATION,
                ),
            ).fetchone()  # fmt: skip
            counts["series"] += 1
            conn.execute(
                """INSERT INTO asset_observation_links (asset_id, observation_id, relationship_type, evidence_reference,
                     verification_status, method_version, provenance_class, scenario_id)
                   VALUES (%s, %s, 'EXPERIMENTAL_SCENARIO_LINK', %s, 'UNVERIFIED', %s, 'SYNTHETIC', %s)""",
                (
                    sensor.asset_id,
                    row[0] if row else None,
                    run.run_id,
                    algorithm,
                    scenario.scenario_id,
                ),
            )
            counts["links"] += 1
        store_decisions(
            conn,
            [
                assignment_decision(
                    run.run_id,
                    scenario.target_asset_id,
                    run.parameter_set_sha256,
                    run.seed,
                    algorithm,
                )
            ],
        )
        counts["events"] = insert_events(conn, field_events(run))
    return counts


def persist_all(
    conn: psycopg.Connection,
    results: dict[str, tuple[FieldRun, list[FieldCheck]]],
    uris: dict[str, str],
    algorithm: str,
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scenario_id, (run, checks) in results.items():
        uri = uris.get(scenario_id, f"{OUTPUT_DIR.as_posix()}/{scenario_id}_telemetry.parquet")
        for key, value in persist_run(conn, run, checks, uri, algorithm).items():
            totals[key] = totals.get(key, 0) + value
    return totals


def main(root: Path = REPO_ROOT) -> int:
    from pipelines.reconcile.run import load_rules

    results = execute_all()
    uris = write_outputs(root, results)
    with connect() as conn:
        totals = persist_all(conn, results, uris, load_rules()["algorithms"]["scenario"])
    for scenario_id, (run, checks) in results.items():
        print(
            f"{scenario_id}: sha256={run.canonical_sha256()} checks={len(checks)} rows={len(run.telemetry)}"
        )
    print(json.dumps(totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
