"""Re-verify the Gate 6 raw batches from disk. Exits 1 if any file is missing, changed, or writable."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pipelines.acquire.common.core import (
    REPO_ROOT,
    FileEntry,
    aggregate_checksum,
    sha256_file,
    utc_now,
)

from .wells import latest_batch

SOURCES = ("carbon_mapper", "naip")


def verify(root: Path, source: str) -> dict[str, Any]:
    manifest = latest_batch(root, source)
    problems = []
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.exists():
            problems.append(f"missing: {entry['path']}")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"sha256 mismatch: {entry['path']}")
        elif os.access(path, os.W_OK):
            problems.append(f"raw file is writable: {entry['path']}")
    recomputed = aggregate_checksum(FileEntry(**f) for f in manifest["files"])
    if recomputed != manifest["original_checksum"]:
        problems.append("aggregate checksum does not match the manifest")
    return {
        "batch_id": manifest["batch_id"],
        "files_verified": len(manifest["files"]),
        "original_checksum": manifest["original_checksum"],
        "integrity_problems": problems,
        "passed": not problems,
    }


def main(root: Path = REPO_ROOT) -> int:
    results = {source: verify(root, source) for source in SOURCES}
    evidence = {
        "validated_at": utc_now(),
        "passed": all(r["passed"] for r in results.values()),
        "sources": results,
    }
    path = root / "reports" / "gates" / "gate_6_validation.json"
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
