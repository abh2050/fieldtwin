"""Score the frozen method on a final split once, and apply the preregistered acceptance rules.

Scoring a final split needs the approved freeze, a completed generation attempt for that split, and a
recorded scoring attempt in the ledger (see attempts.py). Outputs are created exclusively and named
by attempt, so no earlier report, result set, or outcome is ever overwritten:

- reports/diagnostics/final/<attempt>.json: metrics, every acceptance line, and support checks
- data/gold/diagnostics/results/<attempt>.json: per-case rows
- reports/diagnostics/final/outcome-<in-regime attempt>-<held-out attempt>.json: once both are scored

All six preregistered held-out regimes are evaluated by name. A regime with no successful rows, or with
too few, gets INCONCLUSIVE lines, so it can't disappear and let the outcome become MET.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from packages.diagnostics.diagnose import load_method

from . import evaluate as _evaluate
from .attempts import (
    COMPLETED,
    FAILED,
    AttemptRefused,
    begin,
    completed,
    end,
    next_attempt_id,
    write_new,
)
from .cases import ledger_path, prereg
from .freeze import FinalSplitLocked, check_freeze
from .scoring import score

ROOT = _evaluate.ROOT
PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"
FINAL_SPLITS = ("final_in_regime", "final_held_out")


def _line(name: str, value: Any, rule: str, passed: bool, supported: bool = True) -> dict[str, Any]:
    status = (PASS if passed else FAIL) if supported else INCONCLUSIVE
    return {"line": name, "value": value, "rule": rule, "status": status}


def in_regime_lines(m: dict[str, Any], p: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Every in-regime acceptance line, and whether in-regime support meets its minimums."""
    a, s = p["acceptance_in_regime"], p["minimum_support"]["final_in_regime"]
    supported = (
        m.get("primary_cases", 0) >= s["primary_cases"]
        and m.get("no_restriction_cases", 0) >= s["no_restriction_cases"]
    )
    if not supported:
        names = [
            "top1",
            "top1_beats_B1",
            "top3",
            "specificity",
            "miss_rate",
            "joint_success_rate",
            "impact_within_tolerance",
            "impact_median_relative_error",
            "brier_skill_score_vs_climatology",
            "expected_calibration_error",
            "coverage_80_severity",
            "coverage_95_severity",
            "coverage_80_impact",
            "coverage_95_impact",
            "measurement_entropy_reduction",
            "measurement_top1_gain",
            "measurement_against_random",
        ]
        return [_line(n, None, "support below minimum", False, False) for n in names], False
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
            m.get("impact_median_relative_error"),
            f"<= {a['impact_median_relative_error']['at_most']}",
            m.get("impact_median_relative_error") is not None
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
    return lines, True


def held_out_lines(
    by_regime: dict[str, dict[str, Any]], pooled: dict[str, Any], p: dict[str, Any]
) -> list[dict[str, Any]]:
    """Lines for every preregistered regime by name. Missing or under-supported regimes are INCONCLUSIVE."""
    a, s = p["acceptance_held_out"], p["minimum_support"]["final_held_out"]
    band = a["per_regime_coverage_80"]["between"]
    pooled_ok = pooled.get("primary_cases", 0) >= s["pooled_primary_cases"]
    lines = [
        _line(
            "pooled_top1",
            pooled.get("top1"),
            f">= {a['pooled_top1']['at_least']}",
            pooled_ok and pooled["top1"] >= a["pooled_top1"]["at_least"],
            pooled_ok,
        )
    ]
    for regime in p["generator"]["held_out_regimes"]:
        m = by_regime.get(regime) or {"primary_cases": 0}
        supported = m.get("primary_cases", 0) >= s["primary_cases_per_regime"]
        lines.append(
            _line(
                f"{regime}_top1",
                m.get("top1"),
                f">= {a['per_regime_top1']['at_least']}",
                supported and m["top1"] >= a["per_regime_top1"]["at_least"],
                supported,
            )
        )
        for quantity in ("severity", "impact"):
            value = m["coverage_80"][quantity] if supported else None
            lines.append(
                _line(
                    f"{regime}_coverage_80_{quantity}",
                    value,
                    f"in {band}",
                    supported and band[0] <= value <= band[1],
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


def _paths(root: Path, attempt_id: str) -> tuple[Path, Path]:
    return (
        root / "reports" / "diagnostics" / "final" / f"{attempt_id}.json",
        root / "data" / "gold" / "diagnostics" / "results" / f"{attempt_id}.json",
    )


def _score_rows(
    split: str, root: Path, p: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    folder = root / "data" / "gold" / "diagnostics" / split
    manifest = json.loads((folder / "manifest.json").read_text())
    config = load_method(_evaluate.METHOD)
    rows, failures = [], []
    for index, case in enumerate(manifest["cases"]):
        try:
            row = _evaluate.run_case(case["case_id"], split, config, p, index)
        except Exception as error:  # noqa: BLE001 - every failure is kept and reported, never hidden
            failures.append(
                {
                    "case_id": case["case_id"],
                    "regime": case["regime"],
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            continue
        row["regime"] = case["regime"]
        rows.append(row)
    return rows, failures, manifest


def run_split(split: str, root: Path = ROOT, resume_of: str | None = None) -> dict[str, Any]:
    if split not in FINAL_SPLITS:
        raise ValueError("only final splits are scored here")
    record = check_freeze(root)
    ledger = ledger_path(root)
    if not completed(ledger, split, "GENERATE"):
        raise AttemptRefused(f"{split} has no completed generation attempt")
    for path in _paths(root, next_attempt_id(ledger, split, "SCORE")):
        if path.exists():
            raise FileExistsError(f"{path} already exists; it would be overwritten")
    start = begin(ledger, split, "SCORE", root, resume_of)
    report_path, rows_path = _paths(root, start["attempt_id"])
    try:
        p = prereg()
        started = time.perf_counter()
        rows, failures, manifest = _score_rows(split, root, p)
        result: dict[str, Any] = {
            "split": split,
            "attempt_id": start["attempt_id"],
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
            by_regime = {
                regime: score([r for r in rows if r["regime"] == regime], p, regime)
                for regime in p["generator"]["held_out_regimes"]
            }
            pooled = score(rows, p)
            result.update(
                {
                    "metrics_by_regime": by_regime,
                    "metrics_pooled": pooled,
                    "acceptance": held_out_lines(by_regime, pooled, p),
                }
            )
        outputs = {
            str(report_path.relative_to(root)): write_new(
                report_path, json.dumps(result, indent=1, default=str) + "\n"
            ),
            str(rows_path.relative_to(root)): write_new(
                rows_path, json.dumps(rows, indent=1, default=str) + "\n"
            ),
        }
        outputs.update(_write_outcome(root, ledger, split, start["attempt_id"], report_path))
    except BaseException as error:
        end(ledger, start, FAILED, {}, [f"{type(error).__name__}: {error}"])
        raise
    end(ledger, start, COMPLETED, outputs, [], {"rows": len(rows), "failures": len(failures)})
    return result


def _write_outcome(
    root: Path, ledger: Path, split: str, attempt_id: str, report_path: Path
) -> dict[str, str]:
    """Write the outcome once both final splits are scored, named by both attempts."""
    other = "final_held_out" if split == "final_in_regime" else "final_in_regime"
    done = completed(ledger, other, "SCORE")
    if not done:
        return {}
    other_report = _paths(root, done["attempt_id"])[0]
    reports = {split: report_path, other: other_report}
    inside = json.loads(reports["final_in_regime"].read_text())
    held = json.loads(reports["final_held_out"].read_text())
    ids = {split: attempt_id, other: done["attempt_id"]}
    path = (
        root
        / "reports"
        / "diagnostics"
        / "final"
        / f"outcome-{ids['final_in_regime']}-{ids['final_held_out']}.json"
    )
    body = {
        **outcome(inside["acceptance"], inside["support_met"], held["acceptance"]),
        "attempts": ids,
    }
    return {str(path.relative_to(root)): write_new(path, json.dumps(body, indent=1) + "\n")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("split", choices=FINAL_SPLITS)
    parser.add_argument(
        "--resume", help="the incomplete scoring attempt to continue, as recorded in the ledger"
    )
    args = parser.parse_args(argv)
    try:
        result = run_split(args.split, resume_of=args.resume)
    except (FinalSplitLocked, AttemptRefused, FileExistsError) as error:
        print(f"Refused: {error}")
        return 2
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
