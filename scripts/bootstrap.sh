#!/usr/bin/env bash
# Creates the Python environment from uv.lock. Touches no cloud resources.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
uv sync --frozen 2>/dev/null || uv sync
uv run python -c "import duckdb, pandera, pyarrow; print('environment ok, pyarrow', pyarrow.__version__)"
