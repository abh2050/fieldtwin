"""Write reports/portfolio/evaluation_summary.md from the committed result files only.

Every figure is read from a file under reports/, whose path and SHA-256 are listed at the end, so
the summary can't drift from the evidence: tests/unit/test_portfolio.py regenerates it and compares.

    uv run python scripts/portfolio_summary.py
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "portfolio" / "evaluation_summary.md"
SOURCES = {
    "aether_in_regime": "reports/experiments/results/aether_in_regime.json",
    "aether_held_out": "reports/experiments/results/aether_held_out.json",
    "3w_holdout": "reports/experiments/results/3w_holdout.json",
    "gate6": "reports/inspection/results/gate6_summary.json",
    "decisions": "reports/decision/results/decisions.json",
    "economics": "reports/decision/results/economics.json",
    "d1_outcome": "reports/diagnostics/final/outcome-final_in_regime-score-001-final_held_out-score-001.json",
    "d1_in_regime": "reports/diagnostics/final/final_in_regime-score-001.json",
    "d1_held_out": "reports/diagnostics/final/final_held_out-score-001.json",
}


def load(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    data, hashes = {}, {}
    for key, rel in SOURCES.items():
        raw = (root / rel).read_bytes()
        data[key] = json.loads(raw)
        hashes[rel] = hashlib.sha256(raw).hexdigest()
    return data, hashes


def pct(v: float | None) -> str:
    # Half-up rounding, as the web app's screens display.
    return "—" if v is None else f"{math.floor(v * 1000 + 0.5) / 10:.1f}%"


def num(v: float | None, d: int = 3) -> str:
    return "—" if v is None else f"{v:.{d}f}"


def ci(pair: Any, d: int = 2) -> str:
    if not isinstance(pair, list) or len(pair) != 2 or None in pair:
        return "—"
    return f"{pair[0]:.{d}f} to {pair[1]:.{d}f}"


def fmt_line(v: Any) -> str:
    """A D1 acceptance value: a number, an interval, or an estimate with its interval."""
    if isinstance(v, list) and len(v) == 2 and isinstance(v[1], list):
        return f"{num(v[0])} (interval {ci(v[1], 3)})"
    if isinstance(v, list):
        return ci(v, 3)
    return num(v)


def usd(v: float) -> str:
    return f"${v:,.0f}"


def detection(d: dict[str, Any]) -> list[str]:
    held, inr = d["aether_held_out"], d["aether_in_regime"]
    chosen = held["preferred_from_in_regime"]["preferred"]
    lines = [
        "## Gate 5: anomaly detection",
        "",
        f"Two tracks, both evaluated on held-out data after the method was chosen. Selected on the synthetic track: **{chosen}**.",
        "",
        "### Synthetic AETHER track (held-out regimes, pooled)",
        "",
        "| Method | In-regime event recall | Held-out event recall (95%) | Held-out recall by chance | Event skill | False alarms per hour |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, m in held["pooled"].items():
        s, iv = m["summary"], m.get("interval", {})
        r = inr["methods"][name]["summary"]["event_recall"]
        mark = " (selected)" if name == chosen else ""
        lines.append(
            f"| {name}{mark} | {pct(r)} | {pct(s['event_recall'])} ({ci(iv.get('event_recall'))}) | "
            f"{pct(s['chance_event_recall'])} | {num(s['event_skill'], 2)} | {num(s['false_alarms_per_hour'], 4)} |"
        )
    s = held["pooled"][chosen]["summary"]
    lines += [
        "",
        f"The selected detector caught {s['events_detected']} of {s['events']} held-out events. That is weak: "
        "it is better than chance, but it misses more than half.",
        "",
        "### Real Petrobras 3W track (held-out wells)",
        "",
        "| Method | Events detected | Event recall | Recall by chance | Event skill (95%) |",
        "|---|---:|---:|---:|---:|",
    ]
    w3 = d["3w_holdout"]
    w3_chosen = w3["preferred_from_development"]["preferred"]
    for name, m in w3["methods"].items():
        s = m["summary"]
        mark = " (selected)" if name == w3_chosen else ""
        skill_iv = m.get("interval", {}).get("event_skill")
        lines.append(
            f"| {name}{mark} | {s['events_detected']} of {s['events']} | {pct(s['event_recall'])} | "
            f"{pct(s['chance_event_recall'])} | {num(s['event_skill'], 2)} ({ci(skill_iv)}) |"
        )
    above = [
        n
        for n, m in w3["methods"].items()
        if isinstance(m.get("interval", {}).get("event_skill"), list)
        and m["interval"]["event_skill"][0] > 0
    ]
    sel = w3["methods"][w3_chosen]["summary"]
    lines += [
        "",
        f"The method chosen on development wells ({w3_chosen}) caught {sel['events_detected']} of {sel['events']} "
        f"holdout events. Methods whose skill interval lies above zero on the holdout: {', '.join(above) or 'none'}; "
        "the intervals are wide because the holdout has few wells.",
        "",
    ]
    return lines


def aerial(d: dict[str, Any]) -> list[str]:
    a = d["gate6"]["association"]
    rows = a["proximity_vs_matched_null"]
    lines = [
        "## Gate 6: aerial evidence (real public records)",
        "",
        f"{a['plumes']} Carbon Mapper plume origins from {a['scenes_with_plumes']} scenes with plumes ({a['scenes']} scenes searched), "
        "compared with registered wells by distance only.",
        "",
        "| Radius | Plumes with a well inside | Footprint-matched null | Difference (95%) |",
        "|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['radius_m']:.0f} m | {pct(r['plume_share'])} | {pct(r['matched_null_share'])} | "
            f"{pct(r['difference'])} ({pct(r['difference_low'])} to {pct(r['difference_high'])}) |"
        )
    lines += [
        "",
        "Plumes sit nearer registered wells than random points in the same scene footprints. That is proximity, not attribution: "
        "no link names a source, and none was confirmed by a person.",
        "",
    ]
    return lines


def decisions(d: dict[str, Any]) -> list[str]:
    grades = d["decisions"]["grades"]
    econ = d["economics"]
    totals = {k: v["total"] for k, v in econ["summary"].items()}
    cheapest = min(totals, key=lambda k: totals[k]["mean"])
    lines = [
        "## Gate 7: decision support (synthetic)",
        "",
        "| Scenario | Category | Outcome |",
        "|---|---|---|",
    ]
    for g in grades:
        lines.append(
            f"| {g['scenario_id']} | {g['scenario_category']} | {g['outcome'].replace('_', ' ').lower()} |"
        )
    missed = d["decisions"]["faults_without_alarm"]
    if missed:
        for m in missed:
            lines.append(
                f"| {m['scenario_id']} | {m['category']} | no alarm, so no recommendation |"
            )
    lines += [
        "",
        f"Modeled annual cost over {econ['replicates']} replicates ({econ['label']}):",
        "",
        "| Policy | Mean | 5th to 95th percentile |",
        "|---|---:|---:|",
    ]
    for k, t in totals.items():
        lines.append(f"| {k} | {usd(t['mean'])} | {usd(t['p5'])} to {usd(t['p95'])} |")
    lines += [
        "",
        f"The cheapest policy on mean modeled cost was **{cheapest}**: in this model, dispatching on alarms did not pay.",
        "",
    ]
    return lines


def d1(d: dict[str, Any]) -> list[str]:
    outcome = d["d1_outcome"]
    failed = [a for a in d["d1_in_regime"]["acceptance"] if a["status"] == "FAIL"]
    lines = [
        "## D1: model-based restriction diagnosis (synthetic)",
        "",
        f"Outcome: **{outcome['outcome'].replace('_', ' ')}**. Preregistered, frozen, and scored once.",
        "",
        "Failed in-regime line(s): "
        + "; ".join(f"`{a['line']}` = {fmt_line(a['value'])} (rule: {a['rule']})" for a in failed)
        + ".",
        "",
        "| Held-out regime | Top-1 | 80% coverage, severity / impact | Joint success |",
        "|---|---:|---:|---:|",
    ]
    for name, m in d["d1_held_out"]["metrics_by_regime"].items():
        lines.append(
            f"| {name.replace('_', ' ')} | {num(m['top1'])} | {num(m['coverage_80']['severity'])} / "
            f"{num(m['coverage_80']['impact'])} | {num(m['joint_success_rate'])} |"
        )
    lines += [
        "",
        "Near-perfect inside the model it inverts; it fails where telemetry is missing, where a compressor runs outside "
        "its trained range, and its intervals are too narrow at high severity.",
        "",
    ]
    return lines


def render(root: Path = ROOT) -> str:
    data, hashes = load(root)
    lines = [
        "# Evaluation summary",
        "",
        "Generated by `scripts/portfolio_summary.py` from committed result files only. Do not edit by hand.",
        "",
        "> AETHER Field is fictional. Synthetic results come from an uncalibrated model of it and are not evidence "
        "about a real field. Real public records (Petrobras 3W, Carbon Mapper, NAIP, NM OCD) are labelled as such.",
        "",
    ]
    lines += detection(data) + aerial(data) + decisions(data) + d1(data)
    lines += ["## Sources", "", "| File | SHA-256 |", "|---|---|"]
    lines += [f"| `{p}` | `{h}` |" for p, h in hashes.items()]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
