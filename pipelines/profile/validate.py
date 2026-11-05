"""Re-verify acquired data from disk and record Gate 1 evidence. Exits 1 if any check fails."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pipelines.acquire.common.core import REPO_ROOT, git_blob_sha1, sha256_file, utc_now

from .common import FAIL, latest_complete

REQUIRED_SOURCES = ("nm_ocd", "petrobras_3w")


def verify_batch(root: Path, source: str) -> dict[str, Any]:
    """Compare every raw file with its manifest and, where available, its upstream hash."""
    manifest = latest_complete(root, source)
    problems: list[str] = []
    upstream_verified = 0
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.exists():
            problems.append(f"missing: {entry['path']}")
            continue
        if sha256_file(path) != entry["sha256"]:
            problems.append(f"sha256 mismatch: {entry['path']}")
        if os.access(path, os.W_OK):
            problems.append(f"raw file is writable: {entry['path']}")
        upstream = entry.get("upstream_checksum")
        if upstream and upstream.startswith("git-blob-sha1:"):
            if git_blob_sha1(path.read_bytes()) == upstream.split(":", 1)[1]:
                upstream_verified += 1
            else:
                problems.append(f"git blob mismatch: {entry['path']}")

    report = root / "reports" / "data_quality" / f"{source}.json"
    failed_checks = []
    if report.exists():
        contents = json.loads(report.read_text())
        if contents.get("batch_id") != manifest["batch_id"]:
            problems.append("quality report is for a different batch; run `make profile`")
        failed_checks = [c["name"] for c in contents["checks"] if c["status"] == FAIL]
    else:
        problems.append("quality report missing; run `make profile`")

    return {
        "batch_id": manifest["batch_id"],
        "files_verified": len(manifest["files"]),
        "files_verified_against_upstream_hash": upstream_verified,
        "original_checksum": manifest["original_checksum"],
        "accepted_count": manifest["accepted_count"],
        "rejected_count": manifest["rejected_count"],
        "integrity_problems": problems,
        "failed_quality_checks": failed_checks,
        "passed": not problems and not failed_checks,
    }


def main(root: Path = REPO_ROOT) -> int:
    results: dict[str, Any] = {}
    for source in REQUIRED_SOURCES:
        try:
            results[source] = verify_batch(root, source)
        except FileNotFoundError as exc:
            results[source] = {"passed": False, "integrity_problems": [str(exc)]}
    passed = all(r["passed"] for r in results.values())
    evidence = {"validated_at": utc_now(), "passed": passed, "sources": results}
    path = root / "reports" / "gates" / "gate_1_validation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
