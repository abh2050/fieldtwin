"""Gate 7 demonstration: alarms to recommendations to simulated work orders, then grading.

Decision inputs are what an operator would have: detector alarms, the planned-operations calendar,
and open inspection requests. Simulator truth is read only afterwards, by `grade`, to say whether a
work order went to the right place. Writes data/gold/decision/ and reports/decision/results/.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from packages.decision_engine.rules import (
    Action,
    Alarm,
    Context,
    PlannedOperation,
    Recommendation,
    evaluate,
)
from packages.decision_engine.topology import FieldTopology
from packages.decision_engine.workflow import (
    Actor,
    ActorKind,
    Decision,
    WorkOrder,
    create_work_order,
)
from packages.scenario_engine.network_graph import build_graph, load_network
from pipelines.acquire.common import core

from .alarms import SCENARIOS, load_rules, model_checksum, scenario_alarms

GOLD = Path("data") / "gold" / "decision"
RESULTS = Path("reports") / "decision" / "results"
ENGINE = Actor(actor_id="decision-engine", kind=ActorKind.SYSTEM, role="DECISION_ENGINE")


def topology(rules: dict[str, Any]) -> FieldTopology:
    return FieldTopology(
        build_graph(load_network()), rules["consequence"]["parallel_compressor_share"]
    )


def catalog(root: Path) -> dict[str, Any]:
    return core.load_yaml(root / "config" / "scenarios" / "aether_field_scenarios.yaml")


def context_for(scenario_id: str, root: Path) -> Context:
    """The maintenance calendar and open requests. An operator knows these; they aren't truth."""
    data = catalog(root)
    epoch = datetime.fromisoformat(data["simulation"]["simulated_epoch"])
    scenario = next(s for s in data["scenarios"] if s["scenario_id"] == scenario_id)
    planned = [
        PlannedOperation(
            kind=op["kind"],
            asset_id=op["asset_id"],
            start=epoch + timedelta(seconds=op["start_s"]),
            end=epoch + timedelta(seconds=op["end_s"]),
        )
        for op in scenario.get("planned_operations", [])
    ]
    requests_path = root / "data" / "gold" / "inspection" / "inspection_requests.json"
    requests = json.loads(requests_path.read_text()) if requests_path.exists() else []
    open_assets = sorted(
        {
            r["affected_asset_id"]
            for r in requests
            if r["scenario_id"] == scenario_id and r["status"] == "REQUESTED"
        }
    )
    return Context(planned_operations=planned, open_inspection_request_assets=open_assets)


def collect_alarms(root: Path, rules: dict[str, Any], refresh: bool) -> dict[str, dict[str, Any]]:
    """Alarms per scenario, cached by model checksum. The replay takes a few minutes."""
    cache = root / GOLD / "alarms.json"
    key = model_checksum(root, rules)
    if cache.exists() and not refresh:
        stored = json.loads(cache.read_text())
        if stored.get("model_sha256") == key and set(stored["scenarios"]) == set(SCENARIOS):
            return stored["scenarios"]
    scenarios: dict[str, Any] = {}
    for scenario_id in SCENARIOS:
        alarms, meta = scenario_alarms(scenario_id, root, rules)
        scenarios[scenario_id] = {
            "meta": dict(meta) | {"epoch": meta["epoch"].isoformat()},
            "alarms": [a.model_dump(mode="json") for a in alarms],
        }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"model_sha256": key, "scenarios": scenarios}, indent=1) + "\n")
    return scenarios


def demo_decisions(order: WorkOrder, decided_at: datetime, demo: dict[str, Any]) -> None:
    """The scripted approve-all policy. It never reads truth, so false alarms are approved too."""
    supervisor = demo["supervisor"]
    crew = demo["field_crew"]
    approve_at = decided_at + timedelta(hours=supervisor["delay_h"])
    order.apply(
        Decision.APPROVE,
        Actor(
            actor_id=supervisor["actor_id"],
            kind=ActorKind(supervisor["kind"]),
            role=supervisor["role"],
        ),
        supervisor["justification"].strip(),
        approve_at,
    )
    order.apply(
        Decision.COMPLETE,
        Actor(actor_id=crew["actor_id"], kind=ActorKind(crew["kind"]), role=crew["role"]),
        crew["justification"].strip(),
        approve_at + timedelta(hours=crew["complete_after_h"]),
    )


def fault_assets(scenario: dict[str, Any], topo: FieldTopology) -> set[str]:
    """Where the declared fault physically is: the faulted asset, or the assets of a faulted sensor."""
    assets: set[str] = set()
    for fault in scenario.get("physical_faults", []):
        assets.add(fault["asset_id"])
    for fault in scenario.get("sensor_faults", []):
        assets.add(fault["tag"].split(".")[0])
    return assets


def grade(
    recommendation: Recommendation,
    order: WorkOrder | None,
    scenario: dict[str, Any],
    topo: FieldTopology,
) -> dict[str, Any]:
    """Compare a decision with simulator truth. Used only for reporting, never for deciding."""
    truth = fault_assets(scenario, topo)
    category = scenario["category"]
    if order is None:
        outcome = "NOT_DISPATCHED"
        correct = None if not truth else False
    elif not truth:
        outcome = "DISPATCH_WITHOUT_FAULT"
        correct = False
    elif order.asset_id in truth:
        outcome = "DISPATCHED_TO_FAULTED_ASSET"
        correct = True
    elif truth & set(recommendation.candidate_assets):
        outcome = "FAULTED_ASSET_AMONG_CANDIDATES"
        correct = False
    else:
        outcome = "DISPATCHED_ELSEWHERE"
        correct = False
    return {
        "scenario_category": category,
        "faulted_assets": sorted(truth),
        "outcome": outcome,
        "work_order_targets_faulted_asset": correct,
    }


def run(root: Path = core.REPO_ROOT, refresh: bool = False) -> dict[str, Any]:
    rules = load_rules(root)
    demo = core.load_yaml(root / "config" / "decision" / "demo_decisions.yaml")
    topo = topology(rules)
    scenarios = {s["scenario_id"]: s for s in catalog(root)["scenarios"]}
    alarms_by_scenario = collect_alarms(root, rules, refresh)

    recommendations, orders, grades = [], [], []
    for scenario_id in SCENARIOS:
        context = context_for(scenario_id, root)
        open_orders: dict[str, WorkOrder] = {}
        for raw in alarms_by_scenario[scenario_id]["alarms"]:
            alarm = Alarm.model_validate(raw)
            recommendation = evaluate(alarm, context, topo, rules)
            recommendations.append(recommendation)
            order = None
            if recommendation.action in (Action.FIELD_INSPECTION, Action.CHECK_INSTRUMENTATION):
                target = recommendation.candidate_assets[0]
                if target in open_orders:
                    order = open_orders[
                        target
                    ]  # One open work order per asset; the alarm adds evidence.
                else:
                    order = create_work_order(recommendation, ENGINE)
                    demo_decisions(order, recommendation.decided_at, demo)
                    open_orders[target] = order
                    orders.append(order)
            grades.append(
                {
                    "recommendation_id": recommendation.recommendation_id,
                    "scenario_id": scenario_id,
                    "work_order_id": order.work_order_id if order else None,
                    **grade(recommendation, order, scenarios[scenario_id], topo),
                }
            )

    missed = [
        {
            "scenario_id": s,
            "category": scenarios[s]["category"],
            "faulted_assets": sorted(fault_assets(scenarios[s], topo)),
        }
        for s in SCENARIOS
        if fault_assets(scenarios[s], topo) and not alarms_by_scenario[s]["alarms"]
    ]
    out = root / GOLD
    out.mkdir(parents=True, exist_ok=True)
    (out / "recommendations.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in recommendations], indent=1) + "\n"
    )
    (out / "work_orders.json").write_text(
        json.dumps([o.model_dump(mode="json") for o in orders], indent=1) + "\n"
    )
    results = {
        "rules_version": rules["version"],
        "demo_decisions_version": demo["version"],
        "model": {
            "model_id": alarms_by_scenario[SCENARIOS[0]]["alarms"][0]["model_id"]
            if alarms_by_scenario[SCENARIOS[0]]["alarms"]
            else "aether_hist_gradient_boosting",
            "sha256": model_checksum(root, rules),
        },
        "scenarios": {
            s: {
                "scenario_run_id": alarms_by_scenario[s]["meta"]["scenario_run_id"],
                "output_sha256": alarms_by_scenario[s]["meta"]["output_sha256"],
                "category": scenarios[s]["category"],
                "windows": alarms_by_scenario[s]["meta"]["windows"],
                "alarms": len(alarms_by_scenario[s]["alarms"]),
            }
            for s in SCENARIOS
        },
        "recommendations": [r.model_dump(mode="json") for r in recommendations],
        "work_orders": [o.model_dump(mode="json") for o in orders],
        "grades": grades,
        "faults_without_alarm": missed,
    }
    (root / RESULTS).mkdir(parents=True, exist_ok=True)
    (root / RESULTS / "decisions.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n"
    )
    return {
        "recommendations": len(recommendations),
        "by_action": {a.value: sum(r.action is a for r in recommendations) for a in Action},
        "work_orders": len(orders),
        "grades": [(g["scenario_id"], g["outcome"]) for g in grades],
        "faults_without_alarm": [m["scenario_id"] for m in missed],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="replay telemetry even if cached")
    args = parser.parse_args(argv)
    print(json.dumps(run(refresh=args.refresh), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
