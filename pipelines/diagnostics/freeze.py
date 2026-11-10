"""The D1 freeze: which files can change final results, and the guard that keeps final splits locked.

Final cases may be generated only when all of these hold:

1. `config/diagnostics/d1_freeze.yaml` exists and is committed with no local changes.
2. It names this preregistration's SHA-256 and holds a SHA-256 for exactly the protected files below,
   and every protected file on disk matches its recorded hash.
3. Its method commit exists and is an ancestor of the current commit.
4. **Review boundary:** the freeze record and every protected file are identical to the reviewed main
   branch (`origin/main`). A record that exists only on an unmerged branch unlocks nothing.

The protected set is defined here, not in the record, so a record can't leave a file out.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORD = "config/diagnostics/d1_freeze.yaml"
PREREGISTRATION = "config/diagnostics/d1_preregistration.yaml"
MAIN_REF = "origin/main"

# Every file that can change a final result: the plan, the method and its configuration, the diagnosis
# and forward model, measurement selection and update, the port, scoring, the case generator, the
# simulator and the configurations it reads, and the locked dependencies.
PROTECTED = (
    "config/diagnostics/d1_preregistration.yaml",
    "config/diagnostics/d1_method.yaml",
    "config/facility/*.yaml",
    "config/scenarios/*.yaml",
    "config/experiments/aether_benchmark.yaml",
    "packages/diagnostics/*.py",
    "pipelines/diagnostics/*.py",
    "packages/scenario_engine/*.py",
    "packages/domain/*.py",
    "pyproject.toml",
    "uv.lock",
)


def record_digest(record: dict[str, Any]) -> str:
    """Checksum of the record's own contents, so a hand edit to any field is detected."""
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    return hashlib.sha256(yaml.safe_dump(body, sort_keys=True).encode()).hexdigest()


class FinalSplitLocked(RuntimeError):
    """A final split was requested before an approved freeze."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def protected_files(root: Path) -> list[str]:
    """Protected paths that exist, as sorted repository-relative paths."""
    found = set()
    for pattern in PROTECTED:
        for path in root.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                found.add(path.relative_to(root).as_posix())
    return sorted(found)


def file_hashes(root: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in protected_files(root)
    }


def write_record(root: Path = REPO_ROOT, open_questions: list[str] | None = None) -> Path:
    """Write the freeze record for the current commit. Commit it afterwards; it unlocks nothing until merged."""
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    dirty = _git(root, "status", "--porcelain", "--", *protected_files(root)).stdout.strip()
    if not head or dirty:
        raise FinalSplitLocked("commit every protected file before writing the freeze record")
    prereg = yaml.safe_load((root / PREREGISTRATION).read_text())
    hashes = file_hashes(root)
    record = {
        "method_commit": head,
        "preregistration_version": prereg["version"],
        "preregistration_sha256": hashes[PREREGISTRATION],
        "method_config_sha256": hashes["config/diagnostics/d1_method.yaml"],
        "date": date.today().isoformat(),
        "approval": f"Final splits unlock only when this record and every protected file match {MAIN_REF}.",
        "open_questions_for_review": open_questions or [],
        "protected_files": hashes,
    }
    record["record_sha256"] = record_digest(record)
    path = root / RECORD
    header = (
        "# D1 freeze record. Written by pipelines/diagnostics/freeze.py; never edited by hand.\n"
        "# Any change to a protected file, the preregistration, or this record after the freeze is a\n"
        "# protocol change, logged in the preregistration with its timing.\n"
    )
    path.write_text(header + yaml.safe_dump(record, sort_keys=False, width=110))
    return path


def check_freeze(root: Path = REPO_ROOT, main_ref: str = MAIN_REF) -> dict[str, Any]:
    """Raise FinalSplitLocked unless every condition in the module docstring holds."""
    path = root / RECORD
    if not path.exists():
        raise FinalSplitLocked(f"{RECORD} doesn't exist; the method isn't frozen")
    names = protected_files(root)
    if _git(root, "ls-files", "--error-unmatch", RECORD).returncode != 0:
        raise FinalSplitLocked("the freeze record isn't committed")
    dirty = _git(root, "status", "--porcelain", "--", RECORD, *names).stdout.strip()
    if dirty:
        raise FinalSplitLocked(
            f"uncommitted changes to the freeze record or protected files:\n{dirty}"
        )
    record = yaml.safe_load(path.read_text())
    if record.get("record_sha256") != record_digest(record):
        raise FinalSplitLocked("the freeze record was edited by hand; its checksum doesn't match")
    current = file_hashes(root)
    if record.get("preregistration_sha256") != current.get(PREREGISTRATION):
        raise FinalSplitLocked("the freeze record names a different preregistration")
    recorded = record.get("protected_files") or {}
    if set(recorded) != set(current):
        missing, extra = sorted(set(current) - set(recorded)), sorted(set(recorded) - set(current))
        raise FinalSplitLocked(
            f"protected files differ from the record: missing {missing}, unexpected {extra}"
        )
    changed = sorted(name for name in current if recorded[name] != current[name])
    if changed:
        raise FinalSplitLocked(f"protected files changed since the freeze: {changed}")
    method = str(record.get("method_commit", ""))
    if _git(root, "merge-base", "--is-ancestor", method, "HEAD").returncode != 0:
        raise FinalSplitLocked("the recorded method commit isn't an ancestor of the current commit")
    for name, digest in recorded.items():
        shown = subprocess.run(["git", "show", f"{method}:{name}"], cwd=root, capture_output=True)
        if shown.returncode != 0 or hashlib.sha256(shown.stdout).hexdigest() != digest:
            raise FinalSplitLocked(f"{name} at the recorded method commit doesn't match the record")
    if _git(root, "cat-file", "-e", f"{main_ref}:{RECORD}").returncode != 0:
        raise FinalSplitLocked(
            f"the freeze record isn't on {main_ref}; it hasn't been reviewed and merged"
        )
    if _git(root, "diff", "--quiet", main_ref, "--", RECORD, *names).returncode != 0:
        raise FinalSplitLocked(f"the freeze record or protected files differ from {main_ref}")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["write", "check"])
    args = parser.parse_args(argv)
    if args.command == "write":
        print(write_record().relative_to(REPO_ROOT))
        return 0
    try:
        record = check_freeze()
    except FinalSplitLocked as error:
        print(f"Locked: {error}")
        return 2
    print(
        f"Unlocked: method {record['method_commit'][:10]}, {len(record['protected_files'])} protected files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
