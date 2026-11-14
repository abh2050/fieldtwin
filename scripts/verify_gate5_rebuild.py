"""Check that a Gate 5 rebuild reproduced the committed results, then put the committed files back.

A results file also records the commit, hardware, and timings, which differ on every run, so whole
files can't be compared. This compares what Gate 5's reproduction standard covers: every recorded
SHA-256 (scores, model artifacts, dataset, parameter sets) and every metric value. Timings, the
commit, and hardware are ignored.

    python scripts/verify_gate5_rebuild.py BEFORE_DIR AFTER_DIR
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

FILES = ("aether_in_regime.json", "aether_held_out.json")
VARIABLE = {
    "git_sha",
    "hardware",
    "fit_seconds",
    "seconds",
    "median_case_seconds",
    "max_case_seconds",
    "main_run_seconds",
}


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in VARIABLE or key.endswith("_seconds"):
                continue
            out.update(flatten(item, f"{prefix}/{key}"))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{i}]"))
    else:
        if isinstance(value, float):
            value = "NaN" if math.isnan(value) else round(value, 9)  # NaN must equal NaN here
        out[prefix] = value
    return out


def main(before: Path, after: Path) -> int:
    differences: list[str] = []
    checksums = 0
    for name in FILES:
        old = flatten(json.loads((before / name).read_text()))
        new = flatten(json.loads((after / name).read_text()))
        checksums += sum(1 for k in old if k.endswith("sha256"))
        for key in sorted(set(old) | set(new)):
            if old.get(key) != new.get(key):
                differences.append(f"{name}{key}: {old.get(key)!r} -> {new.get(key)!r}")
    if differences:
        print(f"Gate 5 rebuild differs from the committed results in {len(differences)} values:")
        print("\n".join(differences[:20]))
        return 1
    for name in FILES:  # the rebuild reproduced them; keep the committed files exactly
        shutil.copyfile(before / name, after / name)
    print(f"Gate 5 rebuild reproduced every recorded value, including {checksums} checksums.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
