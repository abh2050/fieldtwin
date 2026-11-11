"""Score the frozen method on a final split once, and apply the preregistered acceptance rules.

Refuses unless the freeze guard passes. Writes reports/diagnostics/final/<split>.json with the metrics,
every acceptance line, the support checks, and (once both splits are scored) the outcome label.
Per-case rows go to data/gold/diagnostics/results/. Nothing here changes after the freeze.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from packages.diagnostics.diagnose import load_method

from .cases import OUT, prereg
from .evaluate import METHOD, ROOT, ROWS, run_case
from .freeze import check_freeze
from .scoring import score

FINAL = ROOT / "reports" / "diagnostics" / "final"
PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"


def _line(name: str, value: Any, rule: str, passed: bool, supported: bool = True) -> dict[str, Any]:
    return {
        "line": name,
        "value": value,
        "rule": rule,
        "status": (PASS if passed else FAIL) if supported else INCONCLUSIVE,
    }


def in_regime_lines(m: dict[str, Any], p: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Every in-regime acceptance line, and whether in-regime support meets its minimums."""
    a, s = p["acceptance_in_regime"], p["minimum_support"]["final_in_regime"]
    supported = (
        m["primary_cases"] >= s["primary_cases"]
        and m.get("no_restriction_cases", 0) >= s["no_restriction_cases"]
    )
    cov80, cov95 = a["coverage_80"]["between"], a["coverage_95"]["between"]
    big_supported = m.get("impact_relative_error_cases", 0) >= s["impact_relative_error_cases"]
    lines = [
        _line("top1", m["top1"], f">= {a['top1']['at_least']}", m["top1"] >= a["top1"]["at_least"]),
        _line(
            "top1_beats_B1",
            m["top1_minus_b1_interval"],
            "interval lower end > 0",
            m["top1_minus_b1_interval"][0] > 0,
        ),
        _line("top3", m["top3"], f">= {a['top3']['at_least']}", m["top3"] >= a["top3"]["at_least"]),
        _line(
            "specificity",
            m["specificity"],
            f">= {a['specificity']['at_least']}",
            m["specificity"] >= a["specificity"]["at_least"],
        ),
        _line(
            "miss_rate",
            m["miss_rate"],
            f"<= {a['miss_rate']['at_most']}",
            m["miss_rate"] <= a["miss_rate"]["at_most"],
        ),
        _line(
            "joint_success_rate",
            m["joint_success_rate"],
            f">= {a['joint_success_rate']['at_least']}",
            m["joint_success_rate"] >= a["joint_success_rate"]["at_least"],
        ),
        _line(
            "impact_within_tolerance",
            m["impact_within_tolerance"],
            f">= {a['impact_within_tolerance']['at_least']}",
            m["impact_within_tolerance"] >= a["impact_within_tolerance"]["at_least"],
        ),
        _line(
            "impact_median_relative_error",
            m["impact_median_relative_error"],
            f"<= {a['impact_median_relative_error']['at_most']}",
            m["impact_median_relative_error"] is not None
            and m["impact_median_relative_error"] <= a["impact_median_relative_error"]["at_most"],
            big_supported,
        ),
        _line(
            "brier_skill_score_vs_climatology",
            m["brier_skill_score_vs_climatology"],
            f">= {a['brier_skill_score_vs_climatology']['at_least']}",
            m["brier_skill_score_vs_climatology"]
            >= a["brier_skill_score_vs_climatology"]["at_least"],
        ),
        _line(
            "expected_calibration_error",
            m["expected_calibration_error"],
            f"<= {a['expected_calibration_error']['at_most']}",
            m["expected_calibration_error"] <= a["expected_calibration_error"]["at_most"],
        ),
    ]
    for quantity in ("severity", "impact"):
        lines.append(
            _line(
                f"coverage_80_{quantity}",
                m["coverage_80"][quantity],
                f"in {cov80}",
                cov80[0] <= m["coverage_80"][quantity] <= cov80[1],
            )
        )
        lines.append(
            _line(
                f"coverage_95_{quantity}",
                m["coverage_95"][quantity],
                f"in {cov95}",
                cov95[0] <= m["coverage_95"][quantity] <= cov95[1],
            )
        )
    lines += [
        _line(
            "measurement_entropy_reduction",
            m["measurement_entropy_reduction"],
            f">= {a['measurement_entropy_reduction']['at_least']}",
            m["measurement_entropy_reduction"] >= a["measurement_entropy_reduction"]["at_least"],
        ),
        _line(
            "measurement_top1_gain",
            [m["measurement_top1_gain"], m["measurement_top1_gain_interval"]],
            f">= {a['measurement_top1_gain']['at_least']} and interval lower end > 0",
            m["measurement_top1_gain"] >= a["measurement_top1_gain"]["at_least"]
            and m["measurement_top1_gain_interval"][0] > 0,
        ),
        _line(
            "measurement_against_random",
            m["measurement_against_random_interval"],
            "interval lower end > 0",
            m["measurement_against_random_interval"][0] > 0,
        ),
    ]
    if not supported:
        for line in lines:
            line["status"] = INCONCLUSIVE
    return lines, supported


def held_out_lines(
    by_regime: dict[str, dict[str, Any]], pooled: dict[str, Any], p: dict[str, Any]
) -> list[dict[str, Any]]:
    a, s = p["acceptance_held_out"], p["minimum_support"]["final_held_out"]
    band = a["per_regime_coverage_80"]["between"]
    lines = [
        _line(
            "pooled_top1",
            pooled["top1"],
            f">= {a['pooled_top1']['at_least']}",
            pooled["top1"] >= a["pooled_top1"]["at_least"],
            pooled["primary_cases"] >= s["pooled_primary_cases"],
        )
    ]
    for regime, m in by_regime.items():
        supported = m["primary_cases"] >= s["primary_cases_per_regime"]
        lines.append(
            _line(
                f"{regime}_top1",
                m["top1"],
                f">= {a['per_regime_top1']['at_least']}",
                m["top1"] >= a["per_regime_top1"]["at_least"],
                supported,
            )
        )
        for quantity in ("severity", "impact"):
            value = m["coverage_80"][quantity]
            lines.append(
                _line(
                    f"{regime}_coverage_80_{quantity}",
                    value,
                    f"in {band}",
                    band[0] <= value <= band[1],
                    supported,
                )
            )
    return lines


def outcome(
    in_lines: list[dict[str, Any]], in_supported: bool, held: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """The preregistered outcome labels, with support checked first."""
    if not in_supported:
        return {"outcome": "INCONCLUSIVE", "reason": "in-regime support below its minimum"}
    failed_in = [line["line"] for line in in_lines if line["status"] != PASS]
    if failed_in:
        return {"outcome": "NOT_MET", "failed_in_regime_lines": failed_in}
    if held is None:
        return {"outcome": "PENDING_HELD_OUT"}
    not_passed = [line["line"] for line in held if line["status"] != PASS]
    if not_passed:
        return {
            "outcome": "MET_IN_REGIME_ONLY",
            "held_out_lines_failed_or_inconclusive": not_passed,
        }
    return {"outcome": "MET"}


def run_split(split: str, root: Path = ROOT) -> dict[str, Any]:
    if split not in ("final_in_regime", "final_held_out"):
        raise ValueError("only final splits are scored here")
    record = check_freeze(root)
    p = prereg()
    config = load_method(METHOD)
    manifest = json.loads((OUT / split / "manifest.json").read_text())
    started = time.perf_counter()
    rows, failures = [], []
    for index, case in enumerate(manifest["cases"]):
        try:
            row = run_case(case["case_id"], split, config, p, index)
        except Exception as error:  # noqa: BLE001 - every failure is kept and reported, never hidden
            failures.append(
                {"case_id": case["case_id"], "error": f"{type(error).__name__}: {error}"}
            )
            continue
        row["regime"] = case["regime"]
        rows.append(row)
    result: dict[str, Any] = {
        "split": split,
        "freeze_method_commit": record["method_commit"],
        "preregistration_version": p["version"],
        "cases_in_manifest": len(manifest["cases"]),
        "cases_refused_by_simulator": manifest["refused"],
        "cases_failed_in_diagnosis": failures,
        "seconds": round(time.perf_counter() - started, 1),
    }
    if split == "final_in_regime":
        metrics = score(rows, p)
        lines, supported = in_regime_lines(metrics, p)
        result.update({"metrics": metrics, "acceptance": lines, "support_met": supported})
    else:
        regimes = sorted({r["regime"] for r in rows})
        by_regime = {
            regime: score([r for r in rows if r["regime"] == regime], p) for regime in regimes
        }
        pooled = score(rows, p)
        result.update(
            {
                "metrics_by_regime": by_regime,
                "metrics_pooled": pooled,
                "acceptance": held_out_lines(by_regime, pooled, p),
            }
        )
    FINAL.mkdir(parents=True, exist_ok=True)
    ROWS.mkdir(parents=True, exist_ok=True)
    (FINAL / f"{split}.json").write_text(json.dumps(result, indent=1, default=str) + "\n")
    (ROWS / f"{split}.json").write_text(json.dumps(rows, indent=1, default=str) + "\n")
    in_path, held_path = FINAL / "final_in_regime.json", FINAL / "final_held_out.json"
    if in_path.exists():
        inside = json.loads(in_path.read_text())
        held = json.loads(held_path.read_text())["acceptance"] if held_path.exists() else None
        (FINAL / "outcome.json").write_text(
            json.dumps(outcome(inside["acceptance"], inside["support_met"], held), indent=1) + "\n"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=["final_in_regime", "final_held_out"])
    args = parser.parse_args(argv)
    result = run_split(args.split)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("metrics", "metrics_by_regime", "metrics_pooled")
            },
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
