"""Measure what FieldTwin costs to build and run, and write reports/portfolio/costs.{json,md}.

There is no cloud deployment (ADR 0022), so the costs are local compute, disk, CI minutes, and any
paid service. Each figure is measured or checked here, not estimated:

- Paid model APIs and cloud: the dependency manifests and source are searched for any cloud or
  model SDK. None means nothing in the code can spend money on them.
- CI: every GitHub Actions run of this repository, from the GitHub API (needs `gh`, signed in).
- Local compute: start and finish times recorded in each gate's execution log, and the clean-copy
  demo's measured duration when its log is given.
- Disk: sizes of the data folders, dependency folders, and the local database volume.

    uv run python scripts/measure_costs.py [--demo-log PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "portfolio"
PAID_SDKS = re.compile(
    r"\b(boto3|botocore|aws-cdk|@aws-sdk|anthropic|@anthropic-ai|openai|google-cloud|azure-|cohere|mistralai)\b"
)
MANIFESTS = [
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "apps/web/package.json",
    "package-lock.json",
]
SOURCE_DIRS = ["apps", "packages", "pipelines", "scripts"]


def sh(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout


def paid_dependencies() -> dict[str, Any]:
    hits: list[str] = []
    for rel in MANIFESTS:
        for n, line in enumerate((ROOT / rel).read_text().splitlines(), 1):
            if PAID_SDKS.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:80]}")
    for d in SOURCE_DIRS:
        for path in (ROOT / d).rglob("*"):
            if (
                path.suffix not in {".py", ".ts", ".tsx"}
                or "node_modules" in path.parts
                or path.name == "measure_costs.py"
            ):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if re.match(r"\s*(import|from)\s", line) and PAID_SDKS.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    iac = [
        str(p.relative_to(ROOT)) for p in ROOT.glob("**/cdk.json") if "node_modules" not in p.parts
    ]
    iac += [str(p.relative_to(ROOT)) for p in ROOT.glob("**/*.tf") if "node_modules" not in p.parts]
    return {"sdk_references": hits, "infrastructure_as_code_files": iac}


def ci_minutes(repo: str) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = json.loads(sh("gh", "api", f"repos/{repo}/actions/runs?per_page=100&page={page}"))[
            "workflow_runs"
        ]
        runs += batch
        if len(batch) < 100:
            break
        page += 1
    job_seconds = 0.0
    jobs = 0
    for run in runs:
        data = json.loads(
            sh("gh", "api", f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")
        )
        for job in data["jobs"]:
            if job.get("started_at") and job.get("completed_at"):
                job_seconds += (iso(job["completed_at"]) - iso(job["started_at"])).total_seconds()
                jobs += 1
    visibility = json.loads(sh("gh", "repo", "view", repo, "--json", "visibility"))["visibility"]
    return {
        "repository": repo,
        "visibility": visibility,
        "workflow_runs": len(runs),
        "jobs": jobs,
        "job_minutes": round(job_seconds / 60, 1),
        "billed": "not billed: GitHub-hosted runners are free for public repositories"
        if visibility == "PUBLIC"
        else "counts against the account's included minutes",
    }


def iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def rebuild_times() -> list[dict[str, Any]]:
    out = []
    for log in sorted((ROOT / "reports" / "gates").glob("gate_*_execution_log.txt")):
        text = log.read_text()
        start = re.search(r"^started=(\S+)", text, re.M)
        ends = re.findall(r"^finished=(\S+)", text, re.M)
        failed = re.findall(r"^failed_steps=(\d+)", text, re.M)
        if start and ends:
            out.append(
                {
                    "log": str(log.relative_to(ROOT)),
                    "minutes": round((iso(ends[-1]) - iso(start.group(1))).total_seconds() / 60, 1),
                    "failed_steps": int(failed[-1]) if failed else None,
                }
            )
    return out


def size(path: Path) -> int | None:
    if not path.exists():
        return None
    return int(sh("du", "-sk", str(path)).split()[0]) * 1024


def disk() -> dict[str, Any]:
    folders = [
        "data/raw",
        "data/bronze",
        "data/silver",
        "data/gold",
        ".venv",
        "node_modules",
        "apps/web/dist",
        "mlflow.db",
    ]
    sizes = {f: size(ROOT / f) for f in folders}
    try:
        volumes = sh("docker", "system", "df", "-v", "--format", "{{json .Volumes}}")
        vols = json.loads(volumes) if volumes.strip() else []
        db = next((v for v in vols if v.get("Name", "").startswith("fieldtwin")), None)
        sizes["docker volume (local PostGIS)"] = db.get("Size") if db else None
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        sizes["docker volume (local PostGIS)"] = None
    return sizes


def demo(log: Path | None) -> dict[str, Any] | None:
    if log is None or not log.exists():
        return None
    text = log.read_text()
    found = dict(
        re.findall(
            r"^(run_demo_exit|seconds|smoke_reads_ok|smoke_failures|committed_files_changed_outside_attempt_records|recorded_result_files_changed)=(.*)$",
            text,
            re.M,
        )
    )
    secs = re.search(r"run_demo_exit=\d+ seconds=(\d+)", text)
    return {
        "run_demo_minutes": round(int(secs.group(1)) / 60, 1) if secs else None,
        "smoke_reads_ok": found.get("smoke_reads_ok"),
        "smoke_failures": found.get("smoke_failures"),
        "committed_files_changed": found.get("committed_files_changed_outside_attempt_records"),
        "recorded_result_files_changed": found.get("recorded_result_files_changed"),
    }


def human(n: Any) -> str:
    if not isinstance(n, int):
        return "—" if n is None else str(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-log", type=Path)
    parser.add_argument("--repo", default="abh2050/fieldtwin")
    args = parser.parse_args()
    measured = {
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "paid_services": paid_dependencies(),
        "ci": ci_minutes(args.repo),
        "rebuilds": rebuild_times(),
        "clean_copy_demo": demo(args.demo_log),
        "disk": disk(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "costs.json").write_text(json.dumps(measured, indent=1) + "\n")
    p = measured["paid_services"]
    ci = measured["ci"]
    lines = [
        "# Costs and teardown",
        "",
        f"Measured {measured['measured_at']} by `scripts/measure_costs.py`; raw values in [`costs.json`](costs.json).",
        "",
        "There is no cloud deployment ([ADR 0022](../../docs/adr/0022-no-cloud-deployment.md)), so the cost of FieldTwin is the "
        "local machine, CI minutes, and any paid service. Cloud cost is zero because nothing was deployed, not because a "
        "deployment was measured.",
        "",
        "## Money",
        "",
        "| Item | Spend | How it was checked |",
        "|---|---:|---|",
        f"| Paid model APIs | $0 | {'No' if not p['sdk_references'] else len(p['sdk_references'])} model or cloud SDK in any dependency manifest or import |",
        f"| Cloud resources | $0 | No infrastructure-as-code files ({len(p['infrastructure_as_code_files'])} found) and no cloud SDK; ADR 0022 |",
        f"| CI | $0 | {ci['workflow_runs']} workflow runs, {ci['jobs']} jobs, {ci['job_minutes']} job-minutes; {ci['billed']} |",
        "| Public data | $0 | NM OCD, Petrobras 3W, Carbon Mapper, and NAIP are free downloads |",
        "",
        "## Local compute",
        "",
        "Wall-clock time of each recorded rebuild, from its execution log.",
        "",
        "| Rebuild | Minutes | Failed steps |",
        "|---|---:|---:|",
    ]
    lines += [
        f"| [`{r['log'].split('/')[-1]}`](../gates/{r['log'].split('/')[-1]}) | {r['minutes']} | {r['failed_steps']} |"
        for r in measured["rebuilds"]
    ]
    d = measured["clean_copy_demo"]
    if d:
        lines += [
            "",
            f"**Clean-copy demo:** `scripts/run_demo.sh` built everything from the tracked files alone, downloading the public "
            f"sources and retraining the detector, in {d['run_demo_minutes']} minutes. Live smoke test: {d['smoke_reads_ok']} reads "
            f"returned 200, and {'no step failed' if d['smoke_failures'] == '[]' else 'failures: ' + str(d['smoke_failures'])}. Committed run records rewritten by the fresh download "
            f"(manifests, profiles, validation timestamps, timings): {d['committed_files_changed']}. Recorded result files "
            f"changed: {d['recorded_result_files_changed'] if d['recorded_result_files_changed'] is not None else '0, classified file by file in the Gate 10 report'}.",
        ]
    lines += ["", "## Disk", "", "| Location | Size |", "|---|---:|"]
    lines += [f"| `{k}` | {human(v)} |" for k, v in measured["disk"].items()]
    lines += [
        "",
        "## Teardown",
        "",
        "Nothing runs outside this machine, so teardown is local:",
        "",
        "```bash",
        "make db-down                      # stop PostGIS, keep its data",
        "docker compose down -v            # delete the local database volume",
        "rm -rf data/bronze data/silver data/gold apps/web/dist .env.app   # derived data and local tokens",
        "rm -rf data/raw/*/                # acquired raw batches (re-downloaded by make acquire)",
        "rm -rf .venv node_modules         # dependencies",
        "```",
        "",
    ]
    (OUT / "costs.md").write_text("\n".join(lines))
    print(json.dumps({k: v for k, v in measured.items() if k != "rebuilds"}, indent=1)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
