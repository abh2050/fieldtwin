"""Compare freshly written results with the committed ones: same scores, metrics, and artifacts."""

from __future__ import annotations

import json
import subprocess
import sys

from packages.repositories.database import REPO_ROOT
from pipelines.experiments.common import RESULTS

NAMES = ("3w_development", "3w_holdout", "aether_dataset", "aether_in_regime", "aether_held_out")
VOLATILE = {
    "git_sha",
    "fit_seconds",
    "hardware",
    "load_seconds",
    "max_case_seconds",
    "median_case_seconds",
}


def _committed(name: str) -> dict | None:
    done = subprocess.run(
        ["git", "show", f"HEAD:reports/experiments/results/{name}.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(done.stdout) if done.returncode == 0 else None


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def _hashes(value, prefix: str = "") -> dict[str, str]:
    """Every score and artifact checksum, by path."""
    found = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in (
                "scores_sha256",
                "sha256",
                "dataset_sha256",
                "parameter_sets_sha256",
            ) and isinstance(item, str | dict):
                if isinstance(item, dict):
                    found.update({f"{path}.{k}": v for k, v in item.items()})
                else:
                    found[path] = item
            else:
                found.update(_hashes(item, path))
    return found


def main() -> int:
    failures = 0
    for name in NAMES:
        committed = _committed(name)
        path = RESULTS / f"{name}.json"
        if committed is None or not path.exists():
            print(f"{name}: not compared (missing)")
            continue
        fresh = json.loads(path.read_text())
        before, after = _hashes(committed), _hashes(fresh)
        differing = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        same_metrics = _strip(committed) == _strip(fresh)
        print(
            f"{name}: {len(before)} checksums, {len(differing)} differ; other values identical: {same_metrics}"
        )
        for key in differing[:10]:
            print(f"  differs: {key}")
        failures += bool(differing) + (not same_metrics)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
