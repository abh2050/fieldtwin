#!/usr/bin/env bash
# Runs each command from .github/workflows/ci.yml in a clean copy of the tracked files,
# so a dependence on acquired data or local state fails here. Not a substitute for hosted CI.
set -uo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
REPO="$PWD"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git ls-files -co --exclude-standard | rsync -a --files-from=- ./ "$WORK/"
cd "$WORK" || exit 1
git init -q .
export FIELDTWIN_DB_URL="${FIELDTWIN_DB_URL:-postgresql://fieldtwin:change-me-local-only@127.0.0.1:55432/fieldtwin}"
FAILED=0
run() {
  echo "--- $*"
  "$@" 2>&1 | grep -v Pandas4Warning | tail -"${TAIL:-3}"
  local code=${PIPESTATUS[0]}
  echo "exit=$code"
  [ "$code" -eq 0 ] || FAILED=$((FAILED + 1))
}
echo "clean_copy_files=$(git ls-files -co --exclude-standard | wc -l | tr -d ' ')"
echo "raw_or_bronze_parquet_outside_fixtures=$(find . -path ./data/fixtures -prune -o -name '*.parquet' -print | grep -c . )"
run uv sync --frozen
run uv run ruff check .
run uv run ruff format --check .
run uv run mypy
run uv run pytest tests/unit tests/integration/test_acquisition.py -q
run uv run pytest tests/contract -q
run uv run pytest tests/integration/test_database.py tests/integration/test_reconciliation_db.py -m "db and not acquired" -o addopts=--strict-markers -q
run uv run pytest tests/provenance -m "db and not acquired" -o addopts=--strict-markers -q
uv export --frozen --no-hashes --no-emit-project --format requirements-txt > requirements.txt 2>/dev/null
run uvx pip-audit==2.9.0 --strict --disable-pip --no-deps -r requirements.txt
rm -f requirements.txt
run docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.30.1 detect --source /repo --no-git --redact --no-banner
run docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7 -color=false
echo "failed_ci_commands=$FAILED"
exit "$FAILED"
