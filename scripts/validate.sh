#!/usr/bin/env bash
# Re-verifies acquired data from disk. Exits non-zero if any check fails.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m pipelines.profile.validate
