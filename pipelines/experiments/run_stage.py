"""Run an experiment stage and keep a permanent record of the attempt, whether it succeeds or not.

Each attempt appends one line to `reports/experiments/attempts/attempts.jsonl`, with the command, commit,
whether the tree had uncommitted changes, a hash of every result file before and after, and the exit code.
Its full output goes to a log beside it. Failed attempts are kept, so a rerun can't hide one.

    python -m pipelines.experiments.run_stage 3w-holdout -- pipelines.experiments.three_w_run --stage holdout
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime

from packages.repositories.database import REPO_ROOT
from pipelines.experiments.common import RESULTS

ATTEMPTS = REPO_ROOT / "reports" / "experiments" / "attempts"


def results_state() -> dict[str, str]:
    """SHA-256 of every result file, so any change a stage makes is visible."""
    if not RESULTS.exists():
        return {}
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(RESULTS.glob("*.json"))
    }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()


def _scrub(text: str) -> str:
    text = text.replace(str(REPO_ROOT) + "/", "")
    return re.sub(r"/(Users|home|var/folders|private/tmp)/[^ :\n]*", "<local-path>", text)


def run(stage: str, module: str, arguments: list[str]) -> int:
    ATTEMPTS.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    before = results_state()
    # No warning filter: a ConvergenceWarning is a UserWarning, and hiding it would hide a failed fit.
    command = [sys.executable, "-m", module, *arguments]
    done = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
    output = _scrub(done.stdout + done.stderr)
    log = ATTEMPTS / f"{stamp}-{stage}.log"
    log.write_text(output)
    sys.stdout.write(output)
    after = results_state()
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    record = {
        "stage": stage,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": ["python", "-m", module, *arguments],
        "git_sha": _git("rev-parse", "HEAD"),
        "uncommitted_changes": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "exit_code": done.returncode,
        "results_before_sha256": hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()
        ).hexdigest(),
        "results_after_sha256": hashlib.sha256(
            json.dumps(after, sort_keys=True).encode()
        ).hexdigest(),
        "results_changed": changed,
        "log": log.name,
        "warnings_in_output": sorted(set(re.findall(r"\b(\w+Warning)\b", output))),
    }
    with open(ATTEMPTS / "attempts.jsonl", "a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return done.returncode


def main() -> int:
    if "--" not in sys.argv:
        raise SystemExit("usage: run_stage <stage> -- <module> [arguments]")
    split = sys.argv.index("--")
    stage, module, arguments = sys.argv[1], sys.argv[split + 1], sys.argv[split + 2 :]
    return run(stage, module, arguments)


if __name__ == "__main__":
    raise SystemExit(main())
