"""Committed result files, served with their path and SHA-256 so a reader can check them.

A missing file is reported as not built (with the command that builds it), never replaced.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import ApiError


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ApiError(400, "PATH_OUTSIDE_REPOSITORY", f"{relative} is outside the repository.")
    return path


def read_json(root: Path, relative: str, build: str) -> tuple[Any, dict[str, str]]:
    path = _inside(root, relative)
    if not path.is_file():
        raise ApiError(
            404, "RESULT_NOT_BUILT", f"{relative} has not been built.", {"build_with": build}
        )
    data = path.read_bytes()
    return json.loads(data), {"path": relative, "sha256": hashlib.sha256(data).hexdigest()}


def read_text(root: Path, relative: str, build: str) -> tuple[str, dict[str, str]]:
    path = _inside(root, relative)
    if not path.is_file():
        raise ApiError(
            404, "RESULT_NOT_BUILT", f"{relative} has not been built.", {"build_with": build}
        )
    data = path.read_bytes()
    return data.decode(), {"path": relative, "sha256": hashlib.sha256(data).hexdigest()}


def resolve(root: Path, relative: str) -> Path:
    return _inside(root, relative)
