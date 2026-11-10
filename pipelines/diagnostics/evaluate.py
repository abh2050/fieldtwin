"""Run diagnosis methods on the development or calibration split and score them.

Final splits are never read here. Writes reports/diagnostics/development/<split>_<method>.json.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from packages.diagnostics.baselines import b1_residual
from packages.diagnostics.diagnose import (
    Action,
    MethodConfig,
    diagnose,
    load_method,
    measurement_menu,
    valid_actions,
)

from .cases import DEVELOPMENT_SPLITS, OUT, prereg
from .port import MeasurementPort
from .scoring import score

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "diagnostics" / "development"
ROWS = ROOT / "data" / "gold" / "diagnostics" / "results"
METHOD = ROOT / "config" / "diagnostics" / "d1_method.yaml"


def _summary(d) -> dict[str, Any]:
    return {
        "probabilities": d.probabilities,
        "ranking": d.ranking,
        "severity": d.severity,
        "impact": d.impact,
        "recommendation": d.recommendation,
    }


def run_case(
    case_id: str, split: str, config: MethodConfig, p: dict[str, Any], index: int
) -> dict[str, Any]:
    folder = OUT / split
    telemetry = pd.read_parquet(folder / "telemetry" / f"{case_id}.parquet")
    calendar = json.loads((folder / "calendar" / f"{case_id}.json").read_text())
    diagnosis, diagnoser = diagnose(telemetry, calendar, p, config)
    truth = json.loads((folder / "truth" / f"{case_id}.json").read_text())
    port = MeasurementPort(truth, p)
    rec = diagnosis.recommendation
    assert rec is not None
    action = Action(rec["kind"], rec["target"])
    after = diagnoser.update(action, port.read(action, diagnoser.sensors))
    actions = valid_actions(measurement_menu(p), diagnoser.shut_in)
    rng = np.random.default_rng(int(p["scoring"]["measurement"]["random_action_seed"]) + index)
    random_action = actions[int(rng.integers(len(actions)))]
    after_random = diagnoser.update(
        random_action, MeasurementPort(truth, p).read(random_action, diagnoser.sensors)
    )
    same_type = [a for a in actions if a.kind == action.kind]
    same_type_action = same_type[int(rng.integers(len(same_type)))]
    after_same_type = diagnoser.update(
        same_type_action, MeasurementPort(truth, p).read(same_type_action, diagnoser.sensors)
    )
    flows = {
        w: diagnoser.forward.solve(None, 0.0).edge_flow_sm3_per_s[f"INFLOW:{w}"]
        for w in diagnoser.forward.model.wells
    }

    def deferred(a: Action) -> float:
        """Modeled gas deferred by an action: a shut-in loses the well's flow for its duration."""
        spec = measurement_menu(p)[a.kind]
        return (
            flows.get(a.target, 0.0) * spec.duration_h * 3600
            if spec.burden == "PRODUCTION_INTERRUPTING"
            else 0.0
        )

    return {
        "case_id": case_id,
        "truth": {
            k: truth[k]
            for k in (
                "faulted_pipe",
                "severity",
                "production_impact_sm3_per_s",
                "no_restriction_field_flow_sm3_per_s",
            )
        },
        "diagnosis": _summary(diagnosis),
        "after": _summary(after),
        "random_action": asdict(random_action),
        "after_random": _summary(after_random),
        "same_type_action": asdict(same_type_action),
        "after_same_type": _summary(after_same_type),
        "burden": {
            "recommended_deferred_sm3": deferred(action),
            "random_deferred_sm3": deferred(random_action),
            "recommended_duration_h": measurement_menu(p)[action.kind].duration_h,
            "random_duration_h": measurement_menu(p)[random_action.kind].duration_h,
        },
        "b1": b1_residual(telemetry, p),
        "calibration": diagnosis.calibration,
    }


def evaluate(split: str, config: MethodConfig) -> dict[str, Any]:
    if split not in DEVELOPMENT_SPLITS:
        raise ValueError("only development and calibration splits are evaluated before the freeze")
    p = prereg()
    manifest = json.loads((OUT / split / "manifest.json").read_text())
    started = time.perf_counter()
    rows = [run_case(c["case_id"], split, config, p, i) for i, c in enumerate(manifest["cases"])]
    result = {
        "split": split,
        "method": asdict(config),
        "seconds": round(time.perf_counter() - started, 1),
        "metrics": score(rows, p),
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    ROWS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{split}_{config.name}.json").write_text(
        json.dumps(result, indent=1, default=str) + "\n"
    )
    (ROWS / f"{split}_{config.name}.json").write_text(
        json.dumps(rows, indent=1, default=str) + "\n"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=DEVELOPMENT_SPLITS)
    parser.add_argument("--method", default="frozen", choices=["frozen", "M1_nominal_inversion"])
    args = parser.parse_args(argv)
    config = (
        load_method(METHOD)
        if args.method == "frozen"
        else MethodConfig(name=args.method, calibrate_wells=False)
    )
    result = evaluate(args.split, config)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
