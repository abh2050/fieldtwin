"""Generate D1 cases exactly as config/diagnostics/d1_preregistration.yaml declares.

Development and calibration splits can be generated at any time. A final split is refused unless the
freeze guard in freeze.py passes: every file that can change a result matches the committed freeze
record, and the record and those files are identical to the reviewed main branch.

Each case writes three things, kept apart:
- telemetry/<case>.parquet: what a diagnosis may read (wide permanent-sensor values, NaN when bad)
- calendar/<case>.json: the planned-operations calendar, which an operator knows
- truth/<case>.json: the answer and the true state, read only by scoring and the measurement port
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import zlib
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import yaml

from packages.scenario_engine.benchmark_runs import (
    BenchmarkCase,
    CaseRefused,
    _check_envelope,
    _config_for,
)
from packages.scenario_engine.field_scenarios import FieldScenario, PhysicalFault
from packages.scenario_engine.field_simulation import GOOD, _telemetry, _truth_frame, default_setup
from packages.scenario_engine.network_graph import REPO_ROOT
from packages.scenario_engine.network_solver import NetworkModel, solve_network

from .freeze import FinalSplitLocked, check_freeze

PREREGISTRATION = REPO_ROOT / "config" / "diagnostics" / "d1_preregistration.yaml"
OUT = REPO_ROOT / "data" / "gold" / "diagnostics"
DEVELOPMENT_SPLITS = ("development", "calibration")
FINAL_SPLITS = ("final_in_regime", "final_held_out")


def prereg() -> dict[str, Any]:
    return yaml.safe_load(PREREGISTRATION.read_text())


def prereg_sha256() -> str:
    return hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest()


def _uniform(rng: np.random.Generator, bounds: list[float]) -> float:
    return float(rng.uniform(bounds[0], bounds[1]))


def build_case(split: str, index: int, regime: str = "in_regime") -> BenchmarkCase:
    """One case, fixed by the split, its index, and the preregistration alone."""
    p = prereg()
    g = p["generator"]
    ranges = dict(g["in_regime"])
    if regime != "in_regime":
        ranges.update(g["held_out_regimes"][regime])
    base = g["seed_base"][split]
    if split == "final_held_out":
        base += 10000 * list(g["held_out_regimes"]).index(regime)
    count = (
        g["cases"][split] if split != "final_held_out" else g["cases"]["final_held_out_per_regime"]
    )
    restricted_indices = set(
        np.random.default_rng(base)
        .permutation(count)[: round(g["restriction_share"] * count)]
        .tolist()
    )
    seed = base + index + 1
    rng = np.random.default_rng(np.random.SeedSequence([seed, zlib.crc32(b"D1")]))
    config = default_setup()[0]

    def well_multiplier() -> float:
        if "well_multiplier_bands" in ranges:
            bands = ranges["well_multiplier_bands"]
            return _uniform(rng, bands[int(rng.integers(len(bands)))])
        return _uniform(rng, ranges["well_multiplier"])

    wells = tuple((w.id, round(well_multiplier(), 6)) for w in config.wells)
    noise = round(_uniform(rng, ranges["noise_multiplier"]), 6)
    if "suction_setpoint_bands" in ranges:
        bands = ranges["suction_setpoint_bands"]
        setpoint = _uniform(rng, bands[int(rng.integers(len(bands)))])
    else:
        setpoint = _uniform(rng, ranges["suction_setpoint_pa_abs"])
    units = [u.id for u in config.compression.units]
    capacity = tuple((u.id, u.capacity_sm3_per_s) for u in config.compression.units)
    offline = tuple(units[-ranges["units_offline"] :]) if ranges["units_offline"] else ()
    interval = g["interval_s"]
    physical: tuple[PhysicalFault, ...] = ()
    category = "NONE"
    if index in restricted_indices:
        category = "RESTRICTION"
        onset = int(_uniform(rng, ranges["onset_days"]) * 86400) // interval * interval
        ramp = int(_uniform(rng, ranges["ramp_days"]) * 86400) // interval * interval
        physical = (
            PhysicalFault(
                kind="SEGMENT_RESTRICTION",
                asset_id=str(rng.choice(ranges["restriction_pipes"])),
                onset_s=max(onset, interval),
                full_s=max(onset, interval) + max(ramp, interval),
                max_severity=round(_uniform(rng, ranges["severity"]), 6),
            ),
        )
    return BenchmarkCase(
        case_id=f"d1-{split}-{regime}-{index:03d}",
        split=split,
        regime=regime,
        category=category,
        seed=seed,
        well_multipliers=wells,
        noise_multiplier=noise,
        unit_capacity=capacity,
        units_offline=offline,
        setpoint_steps=((0, round(setpoint, 1)),),
        physical_faults=physical,
    )


def simulate(case: BenchmarkCase) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Telemetry for the diagnosis and the truth for scoring, from the unmodified Gate 4 functions."""
    g = prereg()["generator"]
    _, graph, _, catalog, default_sensors = default_setup()
    offsets = np.arange(0, g["duration_s"], g["interval_s"], dtype=np.int64)
    config = _config_for(case, case.setpoint_steps[0][1])
    model = NetworkModel(config, graph)
    truth, _ = _truth_frame(model, cast(FieldScenario, case), offsets)
    _check_envelope(case, truth, config)
    sensors = [
        dataclasses.replace(s, noise_std=s.noise_std * case.noise_multiplier)
        for s in default_sensors
    ]
    simulation = catalog.simulation.model_copy(update={"seed": case.seed})
    long = _telemetry(
        cast(FieldScenario, case),
        truth,
        model,
        sensors,
        catalog.model_copy(update={"simulation": simulation}),
        case.parameter_sha256(),
        case.run_id,
    )
    good = long["quality"] == GOOD
    wide = long.assign(value=long["value"].where(good)).pivot(
        index="offset_s", columns="tag", values="value"
    )
    wide = wide[[s.tag for s in sensors]].reset_index()
    wide.columns.name = None

    diagnosis_offset = int(offsets[-1])
    state = case.state_at(diagnosis_offset)
    with_fault = solve_network(model, state)
    without = solve_network(model, dataclasses.replace(state, severity=()))
    severity = dict(state.severity)
    pipe = case.physical_faults[0].asset_id if case.physical_faults else "NONE"
    truth_record = {
        "case_id": case.case_id,
        "faulted_pipe": pipe,
        "severity": float(severity.get(pipe, 0.0)),
        "production_impact_sm3_per_s": float(without.total_flow - with_fault.total_flow),
        "no_restriction_field_flow_sm3_per_s": float(without.total_flow),
        "diagnosis_offset_s": diagnosis_offset,
        "true_state": {
            "seed": case.seed,
            "well_multipliers": dict(case.well_multipliers),
            "noise_multiplier": case.noise_multiplier,
            "suction_setpoint_pa_abs": case.setpoint_steps[0][1],
            "units_offline": list(case.units_offline),
            "severity": [[k, v] for k, v in state.severity],
            "shut_in_wells": sorted(state.shut_in_wells),
        },
        "parameters": case.parameters(),
    }
    return wide, truth_record


def calendar(case: BenchmarkCase) -> dict[str, Any]:
    """What an operator knows in advance. Empty for every development and calibration case."""
    return {
        "case_id": case.case_id,
        "planned_operations": [dataclasses.asdict(op) for op in case.planned_operations],
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(split: str, root: Path = REPO_ROOT) -> dict[str, Any]:
    if split in FINAL_SPLITS:
        check_freeze(root)
    elif split not in DEVELOPMENT_SPLITS:
        raise ValueError(f"unknown split {split}")
    g = prereg()["generator"]
    regimes = list(g["held_out_regimes"]) if split == "final_held_out" else ["in_regime"]
    count = (
        g["cases"]["final_held_out_per_regime"] if split == "final_held_out" else g["cases"][split]
    )
    folder = root / "data" / "gold" / "diagnostics" / split
    for sub in ("telemetry", "calendar", "truth"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    entries, refused = [], []
    for regime in regimes:
        for index in range(count):
            case = build_case(split, index, regime)
            try:
                wide, truth = simulate(case)
            except CaseRefused as error:
                refused.append({"case_id": case.case_id, "reason": str(error)})
                continue
            telemetry_path = folder / "telemetry" / f"{case.case_id}.parquet"
            calendar_path = folder / "calendar" / f"{case.case_id}.json"
            truth_path = folder / "truth" / f"{case.case_id}.json"
            wide.to_parquet(telemetry_path, index=False)
            calendar_path.write_text(json.dumps(calendar(case), indent=1) + "\n")
            truth_path.write_text(json.dumps(truth, indent=1) + "\n")
            entries.append(
                {
                    "case_id": case.case_id,
                    "regime": regime,
                    "telemetry_sha256": _sha(telemetry_path),
                    "calendar_sha256": _sha(calendar_path),
                    "truth_sha256": _sha(truth_path),
                }
            )
    manifest = {
        "split": split,
        "preregistration_version": prereg()["version"],
        "preregistration_sha256": prereg_sha256(),
        "cases": entries,
        "refused": refused,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return {"split": split, "cases": len(entries), "refused": len(refused)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=DEVELOPMENT_SPLITS + FINAL_SPLITS)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(generate(args.split), indent=2))
    except FinalSplitLocked as error:
        print(f"Refused: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
