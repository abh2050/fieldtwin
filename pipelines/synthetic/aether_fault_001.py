"""Run AETHER-FAULT-001: simulate both cases, check invariants, write outputs, and record lineage."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import psycopg

from packages.domain.events import EventKind, PrioritizationInput, SharedEvent
from packages.reconciliation.provenance import require_simulated_is_synthetic
from packages.reconciliation.review import store_decisions
from packages.reconciliation.scenario import assignment_decision, require_scenario_source
from packages.repositories.database import REPO_ROOT, connect
from packages.scenario_engine.config import ScenarioConfig, load_config
from packages.scenario_engine.events import run_events
from packages.scenario_engine.invariants import InvariantResult, require_invariants
from packages.scenario_engine.simulate import SimulationRun, simulate
from pipelines.normalize.petrobras_3w_events import insert_events

OUTPUT_DIR = Path("data") / "gold" / "scenarios" / "aether_fault_001"
RUN_TRANSFORMATION = "aether.simulator.to_run@1"
SERIES_TRANSFORMATION = "aether.simulator.to_series@1"


def execute(
    config: ScenarioConfig,
) -> dict[str, tuple[SimulationRun, list[InvariantResult], list[SharedEvent]]]:
    """Simulate every case and refuse any run that breaks a declared invariant."""
    results = {}
    for case in config.cases:
        run = simulate(config, case)
        require_simulated_is_synthetic(run.frame["provenance_class"].iloc[0])
        results[case] = (run, require_invariants(run), run_events(run))
    return results


def prioritization_payload(
    config: ScenarioConfig, run: SimulationRun, events: list[SharedEvent]
) -> dict[str, Any] | None:
    """The input a later workflow will read. It carries no score or recommendation."""
    chosen = [e for e in events if e.event_kind is EventKind.INTEGRATION_PROOF_RULE]
    if not chosen:
        return None
    return PrioritizationInput.from_event(
        chosen[0], " ".join(config.scenario.disclosure.split())
    ).model_dump(mode="json")


def write_outputs(root: Path, config: ScenarioConfig, results: dict[str, Any]) -> dict[str, str]:
    folder = root / OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    uris = {}
    for case, (run, _, events) in results.items():
        path = folder / f"{case}.parquet"
        run.frame.to_parquet(path, index=False)
        uris[case] = (OUTPUT_DIR / f"{case}.parquet").as_posix()
        payload = prioritization_payload(config, run, events)
        if payload:
            (folder / f"{case}_prioritization_input.json").write_text(
                json.dumps(payload, indent=2) + "\n"
            )
    return uris


def _scenario_exists(conn: psycopg.Connection, scenario_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM scenario_runs WHERE scenario_id = %s LIMIT 1", (scenario_id,)
        ).fetchone()
        is not None
    )


def persist(
    conn: psycopg.Connection,
    config: ScenarioConfig,
    results: dict[str, Any],
    uris: dict[str, str],
    algorithm: str,
) -> dict[str, int]:
    """Record runs, per-sensor series, experimental links, assignments, and events."""
    scenario = config.scenario
    if _scenario_exists(conn, scenario.scenario_id):
        return {"already_recorded": 1}
    target_domain = conn.execute(
        """SELECT c.domain FROM assets a JOIN equipment_classes c USING (equipment_class_id)
           WHERE a.asset_id = %s""",
        (scenario.target_well,),
    ).fetchone()
    require_scenario_source("aether_synthetic", target_domain[0] if target_domain else "")
    counts = {"runs": 0, "series": 0, "links": 0, "events": 0, "assignments": 0}
    with conn.transaction():
        conn.execute(
            """INSERT INTO scenarios (scenario_id, scenario_name, scenario_description, target_facility_id, scenario_version, random_seed)
               VALUES (%s, %s, %s, 'AETHER-FIELD', %s, %s)""",
            (
                scenario.scenario_id,
                scenario.name,
                " ".join(scenario.disclosure.split()),
                scenario.version,
                config.simulator.seed,
            ),
        )
        for case, (run, invariants, events) in results.items():
            conn.execute(
                """INSERT INTO scenario_runs (scenario_run_id, scenario_id, case_name, target_asset_id, affected_asset_id,
                     simulator_name, simulator_version, config_sha256, output_sha256, output_uri, random_seed, sample_count,
                     sampling_interval_s, fault_onset_offset_s, parameters, invariants, provenance_class, transformation_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'SYNTHETIC', %s)""",
                (
                    run.run_id, scenario.scenario_id, case, scenario.target_well, scenario.restricted_segment,
                    config.simulator.name, config.simulator.version, config.canonical_sha256(), run.canonical_sha256(),
                    uris[case], config.simulator.seed, len(run.frame), config.sampling.interval_s, run.fault_onset_offset_s,
                    json.dumps(config.model_dump(mode="json")), json.dumps([asdict(i) for i in invariants]), RUN_TRANSFORMATION,
                ),
            )  # fmt: skip
            counts["runs"] += 1
            for sensor in config.sensors:
                record = f"{run.run_id}#{sensor.column}"
                row = conn.execute(
                    """INSERT INTO observations (source_system_id, source_record_id, observation_type, metric_name, unit_id,
                         quality_flag, provenance_class, original_record_uri, sensor_tag_id, value_count, null_count, scenario_id,
                         scenario_run_id, transformation_id)
                       VALUES ('aether_synthetic', %s, 'TELEMETRY_SERIES', %s, %s, 'COMPLETE', 'SYNTHETIC', %s, %s, %s, 0, %s, %s, %s)
                       RETURNING observation_id""",
                    (record, sensor.tag, sensor.unit, f"{uris[case]}#column={sensor.column}", f"aether_synthetic:{sensor.tag}",
                     len(run.frame), scenario.scenario_id, run.run_id, SERIES_TRANSFORMATION),
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
            counts["assignments"] += store_decisions(
                conn,
                [
                    assignment_decision(
                        run.run_id,
                        scenario.target_well,
                        config.canonical_sha256(),
                        config.simulator.seed,
                        algorithm,
                    )
                ],
            )
            counts["events"] += insert_events(conn, events)
    return counts


def main(root: Path = REPO_ROOT) -> int:
    from pipelines.reconcile.run import load_rules

    config = load_config()
    results = execute(config)
    uris = write_outputs(root, config, results)
    with connect() as conn:
        counts = persist(conn, config, results, uris, load_rules()["algorithms"]["scenario"])
    for case, (run, invariants, events) in results.items():
        print(
            f"{case}: sha256={run.canonical_sha256()} invariants={len(invariants)} events={len(events)}"
        )
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
