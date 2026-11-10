"""Run the modeled scheduling comparison and its sensitivity analysis.

All outputs are modeled scenario estimates for fictional AETHER Field under the assumptions in
config/decision/economics.yaml. They are not realized or expected savings for any real operation.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from packages.decision_engine.economics import (
    STRATEGIES,
    Asset,
    DetectorStats,
    costs,
    draw_year,
    simulate,
)
from packages.optimization.routing import Router
from packages.scenario_engine.field_simulation import simulate_by_id
from pipelines.acquire.common import core

from .alarms import load_rules
from .run import topology

RESULTS = Path("reports") / "decision" / "results"
STATION = "STATION"
MCF_PER_SM3 = 35.3147 / 1000


def load_config(root: Path) -> dict[str, Any]:
    return core.load_yaml(root / "config" / "decision" / "economics.yaml")


def detector_stats(root: Path, cfg: dict[str, Any]) -> DetectorStats:
    pooled = json.loads((root / cfg["detector_results"]).read_text())["pooled"][
        cfg["detector_method"]
    ]
    by_category = pooled["by_category"]
    sensor = [k for k in by_category if k.startswith("SENSOR")]
    share = {
        k: v["detected"] / v["events"] for k, v in by_category.items() if not k.startswith("SENSOR")
    }
    share["SENSOR"] = sum(by_category[k]["detected"] for k in sensor) / sum(
        by_category[k]["events"] for k in sensor
    )
    delays = {k: (v["q25_hours"], v["q75_hours"]) for k, v in pooled["delays"].items()}
    return DetectorStats(share, delays, pooled["summary"]["false_alarms_per_hour"])


def field_assets(rules: dict[str, Any]) -> tuple[list[Asset], list[str], Any]:
    topo = topology(rules)
    normal = simulate_by_id("AETHER-NET-NORMAL").truth
    flow = {
        column.removeprefix("truth_q_"): float(normal[column].median()) * 86400 * MCF_PER_SM3
        for column in normal.columns
        if column.startswith("truth_q_")
    }
    assets = []
    for fact in topo.facts.values():
        if fact.kind == "well":
            pad = f"PAD-{fact.asset_id[0]}"
            assets.append(
                Asset(fact.asset_id, "well", fact.asset_id, pad, flow[f"FL-{fact.asset_id}"])
            )
        elif fact.kind == "flowline":
            well = fact.asset_id.removeprefix("FL-")
            assets.append(
                Asset(fact.asset_id, "flowline", well, f"PAD-{well[0]}", flow[fact.asset_id])
            )
        elif fact.kind == "gathering_segment":
            group = {"GS-A": "PAD-A", "GS-B": "PAD-B"}.get(fact.asset_id, "TRUNK")
            assets.append(
                Asset(fact.asset_id, "gathering_segment", fact.asset_id, group, flow[fact.asset_id])
            )
        elif fact.kind == "compressor":
            assets.append(Asset(fact.asset_id, "compressor", STATION, STATION, flow[fact.asset_id]))
    sites = sorted({a.site for a in assets})

    def distance_m(a: str, b: str) -> float:
        a = "C-01" if a == STATION else a
        b = "C-01" if b == STATION else b
        return topo.distance_m(a, b)

    return sorted(assets, key=lambda a: a.asset_id), sites, distance_m


def run_strategies(
    cfg: dict[str, Any], stats: DetectorStats, assets, sites, distance_m, replicates: int
) -> dict[str, list[dict[str, float]]]:
    router = Router(
        distance_m, "MAINT-BASE", cfg["strategies"]["ROUTE_OPTIMIZED"]["solver_time_limit_s"]
    )
    outcomes: dict[str, list[dict[str, float]]] = {s: [] for s in STRATEGIES}
    seeds = np.random.SeedSequence(cfg["seed"]).spawn(replicates)
    for seed in seeds:
        draw_seed, inspect_seed = seed.spawn(2)
        faults, jobs = draw_year(assets, sites, cfg, stats, np.random.default_rng(draw_seed))
        for strategy in STRATEGIES:
            # Every strategy reuses one inspection stream, so finds differ only by schedule.
            rng = np.random.default_rng(inspect_seed)
            totals = simulate(
                strategy, faults, jobs, sites, cfg, distance_m, router.tour, "MAINT-BASE", rng
            )
            outcomes[strategy].append(costs(totals, cfg))
    outcomes["_solver_calls"] = [{"calls": float(router.solver_calls)}]
    return outcomes


def summarize(outcomes: dict[str, list[dict[str, float]]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for strategy in STRATEGIES:
        rows = outcomes[strategy]
        summary[strategy] = {
            key: {
                "mean": float(np.nanmean([r[key] for r in rows])),
                "p5": float(np.nanpercentile([r[key] for r in rows], 5)),
                "p50": float(np.nanpercentile([r[key] for r in rows], 50)),
                "p95": float(np.nanpercentile([r[key] for r in rows], 95)),
            }
            for key in rows[0]
        }
    for strategy in STRATEGIES[1:]:
        diff = [
            b["total"] - a["total"]
            for a, b in zip(outcomes["FIXED"], outcomes[strategy], strict=True)
        ]
        summary[strategy]["total_minus_fixed"] = {
            "mean": float(np.mean(diff)),
            "p5": float(np.percentile(diff, 5)),
            "p95": float(np.percentile(diff, 95)),
            "share_of_replicates_cheaper": float(np.mean(np.array(diff) < 0)),
        }
    diff = [
        b["total"] - a["total"]
        for a, b in zip(outcomes["RISK_BASED"], outcomes["ROUTE_OPTIMIZED"], strict=True)
    ]
    summary["ROUTE_OPTIMIZED"]["total_minus_risk_based"] = {
        "mean": float(np.mean(diff)),
        "p5": float(np.percentile(diff, 5)),
        "p95": float(np.percentile(diff, 95)),
        "share_of_replicates_cheaper": float(np.mean(np.array(diff) < 0)),
    }
    return summary


def _scaled(cfg: dict[str, Any], path: str, factor: float) -> dict[str, Any]:
    changed = copy.deepcopy(cfg)
    *parents, leaf = path.split(".")
    node = changed
    for key in parents:
        node = node[key]
    if isinstance(node[leaf], dict):
        node[leaf] = {k: v * factor for k, v in node[leaf].items()}
    else:
        node[leaf] = node[leaf] * factor
        if leaf in ("finds_physical_fault", "localization_correct", "deferred_share_while_faulted"):
            node[leaf] = min(node[leaf], 1.0)
    return changed


def run(root: Path = core.REPO_ROOT) -> dict[str, Any]:
    cfg = load_config(root)
    rules = load_rules(root)
    stats = detector_stats(root, cfg)
    assets, sites, distance_m = field_assets(rules)
    started = time.perf_counter()
    main = run_strategies(cfg, stats, assets, sites, distance_m, cfg["replicates"])
    elapsed = time.perf_counter() - started
    summary = summarize(main)

    sensitivity = []
    for path in cfg["sensitivity"]["assumptions"]:
        for factor in cfg["sensitivity"]["factors"]:
            scaled = _scaled(cfg, path, factor)
            result = summarize(
                run_strategies(scaled, stats, assets, sites, distance_m, cfg["replicates"])
            )
            means = {s: result[s]["total"]["mean"] for s in STRATEGIES}
            sensitivity.append(
                {
                    "assumption": path,
                    "factor": factor,
                    "mean_total": means,
                    "cheapest": min(means, key=lambda s: means[s]),
                    "route_minus_risk_based_mean": result["ROUTE_OPTIMIZED"][
                        "total_minus_risk_based"
                    ]["mean"],
                }
            )
    output = {
        "economics_version": cfg["version"],
        "rules_version": rules["version"],
        "replicates": cfg["replicates"],
        "seed": cfg["seed"],
        "horizon_days": cfg["horizon_days"],
        "label": "Modeled scenario estimates for a fictional facility. Not realized or expected savings.",
        "detector": {
            "method": cfg["detector_method"],
            "detect_share": stats.detect_share,
            "delay_quartiles_h": stats.delay_quartiles_h,
            "false_alarms_per_hour": stats.false_alarms_per_hour,
        },
        "assets": [
            {
                "asset_id": a.asset_id,
                "class": a.asset_class,
                "site": a.site,
                "flow_mcf_per_day": round(a.flow_mcf_per_day, 2),
            }
            for a in assets
        ],
        "sites": sites,
        "summary": summary,
        "sensitivity": sensitivity,
        "solver_calls_main": main["_solver_calls"][0]["calls"],
        "main_run_seconds": round(elapsed, 1),
    }
    (root / RESULTS).mkdir(parents=True, exist_ok=True)
    (root / RESULTS / "economics.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    return {
        s: {
            k: round(summary[s][k]["mean"], 1)
            for k in (
                "total",
                "travel",
                "labor",
                "deferred_production",
                "physical_repaired",
                "physical_faults",
                "mean_hours_to_repair",
                "trips_finding_nothing",
            )
        }
        for s in STRATEGIES
    } | {"seconds": round(elapsed, 1)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
