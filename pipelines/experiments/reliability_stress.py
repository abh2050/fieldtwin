"""Controlled repeated runs. Passing shows no hang recurred here, and doesn't explain the Gate 4 hang."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from packages.repositories.database import REPO_ROOT
from packages.scenario_engine.execution import ExecutionReport, Outcome, run_with_timeout
from pipelines.experiments.common import EXPERIMENTS, hardware, write_result

MODULE = "packages.scenario_engine.execution:"
HASHES = REPO_ROOT / "config" / "scenarios" / "aether_field_expected_hashes.yaml"


def _expected() -> dict[str, str]:
    loaded = yaml.safe_load(Path(HASHES).read_text())
    return loaded.get("hashes", loaded)


def run(repeats: int, workers: int) -> dict:
    expected = _expected()
    jobs = [
        (MODULE + "gate4_scenario", {"scenario_id": s}, f"{s}#{i}", 180.0)
        for s in expected
        for i in range(repeats)
    ]
    jobs += [
        (MODULE + "propagation_comparison", {}, f"propagation#{i}", 180.0) for i in range(repeats)
    ]
    log_path = EXPERIMENTS / "reliability_stress_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as log, ThreadPoolExecutor(workers) as pool:
        reports: list[ExecutionReport] = list(
            pool.map(
                lambda j: run_with_timeout(j[0], j[1], timeout_s=j[3], label=j[2], log=log), jobs
            )
        )
        forced = {
            "SOLVER_NONCONVERGENCE": run_with_timeout(
                MODULE + "forced_nonconvergence",
                {},
                timeout_s=120,
                label="forced_nonconvergence",
                log=log,
            ),
            "INFEASIBLE_STATE": run_with_timeout(
                MODULE + "forced_infeasible", {}, timeout_s=120, label="forced_infeasible", log=log
            ),
            "EXECUTION_TIMEOUT": run_with_timeout(
                MODULE + "forced_hang", {}, timeout_s=5, label="forced_hang", log=log
            ),
            "CRASH": run_with_timeout(
                MODULE + "forced_crash", {}, timeout_s=120, label="forced_crash", log=log
            ),
        }
    outcomes: dict[str, int] = {}
    scenarios: dict[str, dict] = {}
    for report in reports:
        outcomes[report.outcome.value] = outcomes.get(report.outcome.value, 0) + 1
        name = report.label.split("#")[0]
        row = scenarios.setdefault(
            name,
            {
                "runs": 0,
                "ok": 0,
                "hash_matches": 0,
                "max_seconds": 0.0,
                "max_newton_iterations": None,
            },
        )
        row["runs"] += 1
        row["max_seconds"] = round(max(row["max_seconds"], report.elapsed_s), 3)
        if report.outcome is Outcome.OK and report.result is not None:
            row["ok"] += 1
            if name in expected and report.result["sha256"] == expected[name]:
                row["hash_matches"] += 1
            if "max_newton_iterations" in report.result:
                row["max_newton_iterations"] = report.result["max_newton_iterations"]
    return {
        "repeats_per_target": repeats,
        "workers": workers,
        "total_runs": len(reports),
        "outcomes": outcomes,
        "scenarios": scenarios,
        "forced_failures": {
            k: {
                "observed": v.outcome.value,
                "matches": v.outcome.value == k,
                "elapsed_s": round(v.elapsed_s, 3),
                "stack_captured": bool(v.stack),
            }
            for k, v in forced.items()
        },
        "hardware": hardware(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    result = run(args.repeats, args.workers)
    write_result("reliability_stress", result)
    print(result["outcomes"], {k: v["observed"] for k, v in result["forced_failures"].items()})
    return (
        0
        if set(result["outcomes"]) == {"OK"}
        and all(v["matches"] for v in result["forced_failures"].values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
