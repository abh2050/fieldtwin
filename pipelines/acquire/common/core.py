"""Shared acquisition plumbing: paths, hashing, manifests, quarantine, logs, failure reports."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import sys
import traceback
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from .errors import InsufficientDisk

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPLETE = "COMPLETE"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(data: bytes) -> str:
    """The SHA-1 Git assigns a file, which lets us check bytes against the commit tree."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def preflight_disk(
    path: Path,
    needed_bytes: int,
    floor_bytes: int,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> int:
    """Raise before downloading if the transfer would leave less than the floor free."""
    path.mkdir(parents=True, exist_ok=True)
    free = disk_usage(path).free
    if free - needed_bytes < floor_bytes:
        raise InsufficientDisk(
            f"{free} bytes free, {needed_bytes} needed, floor is {floor_bytes}. Nothing downloaded."
        )
    return free


def freeze_tree(path: Path) -> None:
    """Mark raw files read-only. Directories stay writable so a batch can be removed on purpose."""
    for item in path.rglob("*"):
        if item.is_file():
            item.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


@dataclass
class FileEntry:
    path: str
    sha256: str
    size_bytes: int
    source_url: str
    source_modified: str | None = None
    upstream_checksum: str | None = None


@dataclass
class BatchManifest:
    """Mirrors the `ingestion_batches` entity, plus the file list needed to re-verify a batch."""

    batch_id: str
    source_system_id: str
    source_version: str
    config_sha256: str
    ingestion_timestamp: str
    original_checksum: str
    source_record_count: int
    accepted_count: int
    rejected_count: int
    processing_status: str
    manifest_uri: str
    license: dict[str, Any]
    files: list[FileEntry] = field(default_factory=list)
    datasets: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def aggregate_checksum(files: Iterable[FileEntry]) -> str:
    joined = "\n".join(f"{f.sha256}  {f.path}" for f in sorted(files, key=lambda f: f.path))
    return hashlib.sha256(joined.encode()).hexdigest()


def manifest_path(root: Path, source: str, batch_id: str) -> Path:
    return root / "data" / "manifests" / source / f"{batch_id}.json"


def write_manifest(manifest: BatchManifest, root: Path) -> Path:
    path = manifest_path(root, manifest.source_system_id, manifest.batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(manifest), indent=2) + "\n")
    os.replace(temp, path)
    return path


def load_manifests(root: Path, source: str) -> list[dict[str, Any]]:
    folder = root / "data" / "manifests" / source
    return [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]


def find_complete(root: Path, source: str, config_sha: str) -> dict[str, Any] | None:
    """Latest finished batch for this exact configuration whose raw files are still on disk."""
    matches = [
        m
        for m in load_manifests(root, source)
        if m["processing_status"] == COMPLETE
        and m["config_sha256"] == config_sha
        and all((root / f["path"]).exists() for f in m["files"])
    ]
    return max(matches, key=lambda m: m["ingestion_timestamp"]) if matches else None


def completed_batch(root: Path, source: str, batch_id: str) -> dict[str, Any] | None:
    """Return this exact batch if finished and on disk. Finished raw batches are never rewritten."""
    path = manifest_path(root, source, batch_id)
    if not path.exists():
        return None
    manifest = json.loads(path.read_text())
    finished = manifest["processing_status"] == COMPLETE
    return (
        manifest
        if finished and all((root / f["path"]).exists() for f in manifest["files"])
        else None
    )


class Quarantine:
    """Invalid records go here with a reason. Records are never dropped silently."""

    def __init__(self, path: Path):
        self.path = path
        self.count = 0
        self.reasons: dict[str, int] = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    def add(self, dataset: str, reason: str, record: dict[str, Any]) -> None:
        self.count += 1
        self.reasons[f"{dataset}:{reason}"] = self.reasons.get(f"{dataset}:{reason}", 0) + 1
        with self.path.open("a") as handle:
            handle.write(
                json.dumps({"dataset": dataset, "reason": reason, "record": record}, default=str)
                + "\n"
            )


def write_string_parquet(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Bronze keeps original lexical values, so every column is a nullable string."""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(c, pa.string()) for c in columns])
    data = {c: [None if r.get(c) is None else str(r[c]) for r in rows] for c in columns}
    pq.write_table(pa.Table.from_pydict(data, schema=schema), path, compression="zstd")


def write_failure_report(
    root: Path, source: str, batch_id: str | None, stage: str, error: Exception
) -> Path:
    """Record a failed run. The caller exits non-zero and no replacement data is produced."""
    path = root / "reports" / "ingestion" / f"{source}_failure_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "source_system_id": source,
        "batch_id": batch_id,
        "processing_status": "FAILED",
        "stage": stage,
        "error_type": type(error).__name__,
        "error": str(error),
        "occurred_at": utc_now(),
        "substitute_data_produced": False,
        "traceback": traceback.format_exc(limit=5),
    }
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": utc_now(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log(logger: logging.Logger, message: str, **fields: Any) -> None:
    logger.info(message, extra={"fields": fields})
