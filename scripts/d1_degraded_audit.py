"""Audit extract for the D1 degraded-operations finding. Evidence only: reads frozen results, changes nothing.

Reads the held-out per-case results and case truth that the final scoring attempt produced. Refuses
unless the results file's SHA-256 matches the hash recorded in the attempt ledger's END event. Writes
reports/diagnostics/final/degraded_operations_audit.json: one row per degraded-operations case with
the fault and dropout pads, shut-in wells, the top-ranked hypothesis, whether it was right, and the
probabilities given to it and to the true pipe, plus the summary counts the final report quotes.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "reports/diagnostics/final/attempts.jsonl"
ATTEMPT = "final_held_out-score-001"
ROWS = "data/gold/diagnostics/results/final_held_out-score-001.json"
TRUTH = ROOT / "data/gold/diagnostics/final_held_out/truth"
OUT = ROOT / "reports/diagnostics/final/degraded_operations_audit.json"
REGIME = "degraded_operations"


def recorded_hash() -> str:
    for line in LEDGER.read_text().splitlines():
        event = json.loads(line)
        if event["event"] == "END" and event["attempt_id"] == ATTEMPT and event["status"] == "COMPLETED":
            return event["outputs"][ROWS]
    raise SystemExit(f"no completed {ATTEMPT} in the ledger")


def pad_of(pipe: str) -> str | None:
    if pipe.startswith("FL-"):
        return f"PAD-{pipe[3]}"
    if pipe in ("GS-A", "GS-B"):
        return f"PAD-{pipe[-1]}"
    return None  # GS-TRUNK and NONE belong to no pad


def main() -> int:
    data = (ROOT / ROWS).read_bytes()
    actual, expected = hashlib.sha256(data).hexdigest(), recorded_hash()
    if actual != expected:
        raise SystemExit(f"{ROWS} doesn't match the ledger: {actual} against {expected}")
    rows = [r for r in json.loads(data) if r["regime"] == REGIME]
    cases = []
    for row in rows:
        truth = json.loads((TRUTH / f"{row['case_id']}.json").read_text())
        dropout = re.search(r"group='(PAD-\w)'", " ".join(truth["parameters"]["communication_faults"]))
        pipe = truth["faulted_pipe"]
        shut = truth["true_state"]["shut_in_wells"]
        top = row["diagnosis"]["ranking"][0]
        probabilities = row["diagnosis"]["probabilities"]
        if pipe == "NONE":
            relation = "no restriction"
        elif pad_of(pipe) is None:
            relation = "fault on no pad"
        else:
            relation = "fault on the dropped pad" if pad_of(pipe) == (dropout.group(1) if dropout else None) else "fault on the other pad"
            if pipe.startswith("FL-") and pipe[3:] in shut:
                relation += ", own well shut in"
        cases.append({
            "case_id": row["case_id"],
            "faulted_pipe": pipe,
            "fault_pad": pad_of(pipe),
            "dropout_pad": dropout.group(1) if dropout else None,
            "shut_in_wells": shut,
            "relation": relation,
            "top_ranked": top,
            "correct": top == pipe,
            "probability_of_top": round(probabilities[top], 6),
            "probability_of_true": round(probabilities.get(pipe, 0.0), 6),
        })
    summary: dict[str, dict[str, int]] = {}
    for case in cases:
        entry = summary.setdefault(case["relation"], {"cases": 0, "correct": 0})
        entry["cases"] += 1
        entry["correct"] += case["correct"]
    restriction = [c for c in cases if c["faulted_pipe"] != "NONE"]
    wrong = [c for c in restriction if not c["correct"]]
    output = {
        "purpose": "Evidence for the degraded-operations finding in reports/diagnostics/final_report.md. Read-only extract; nothing was rescored.",
        "source_results": ROWS,
        "source_results_sha256": actual,
        "ledger_attempt": ATTEMPT,
        "ledger_recorded_sha256": expected,
        "summary_by_relation": summary,
        "restriction_cases_top1": f"{len(restriction) - len(wrong)} of {len(restriction)}",
        "mean_probability_of_top_when_wrong": round(sum(c["probability_of_top"] for c in wrong) / len(wrong), 4) if wrong else None,
        "cases": cases,
    }
    OUT.write_text(json.dumps(output, indent=1) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "cases"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
