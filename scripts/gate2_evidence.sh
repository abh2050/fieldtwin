#!/usr/bin/env bash
# Rebuilds the local database from nothing and records actual output as Gate 2 evidence.
# Deletes only this project's local Docker volume. Needs data from `make acquire`.
set -uo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
OUT=reports/gates/gate_2_execution_log.txt
mkdir -p reports/gates
: > "$OUT"
FAILED=0

step() {
  local name="$1"
  shift
  { echo; echo "=== $name"; echo "\$ $*"; } | tee -a "$OUT"
  "$@" 2>&1 | grep -v 'Pandas4Warning' | sed -E -e "s#$PWD/##g" -e 's#/(var/folders|private/tmp)/[^ :]*#<temp-dir>#g' | tee -a "$OUT"
  local code=${PIPESTATUS[0]}
  echo "exit=$code" | tee -a "$OUT"
  [ "$code" -eq 0 ] || FAILED=$((FAILED + 1))
}

{ echo "Gate 2 execution log"; echo "started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"

step "Fresh database" docker compose down -v
step "Start PostGIS" docker compose up -d --wait postgres
step "Migrate" uv run python -m packages.repositories.database
step "Migrate again (expect none applied)" uv run python -m packages.repositories.database
step "Seed" uv run python -m pipelines.normalize.seed
step "Source schemas from acquired data" uv run python -m pipelines.profile.source_schemas
step "Load real batches" uv run python -m pipelines.normalize.load
step "Load again (expect already_loaded)" uv run python -m pipelines.normalize.load
step "Canonical validation" uv run python -m pipelines.normalize.validate_canonical
step "Generate reports" uv run python -m pipelines.normalize.reports
step "Generate schema document" uv run python -m pipelines.normalize.schema_docs
step "Dump schema" bash -c 'docker compose exec -T postgres pg_dump -U fieldtwin -d fieldtwin --schema-only --no-owner --no-privileges | grep -v "^\\\\\(un\)\?restrict" > db/ddl/schema.sql && wc -l db/ddl/schema.sql'
step "Bronze quality reports" uv run python -m pipelines.profile.cli
step "Raw integrity" uv run python -m pipelines.profile.validate
step "Ruff lint" uv run ruff check .
step "Ruff format" uv run ruff format --check .
step "Mypy" uv run mypy
step "Unit and offline tests" uv run pytest -q
step "Contract tests (CI job)" uv run pytest tests/contract -q
step "PostgreSQL integration tests (CI job)" uv run pytest tests/integration/test_database.py -m "db and not acquired" -o addopts=--strict-markers -q
step "Provenance invariants (CI job)" uv run pytest tests/provenance -m "db and not acquired" -o addopts=--strict-markers -q
step "Tests on real canonical data" uv run pytest -m "acquired" -o addopts=--strict-markers -q
step "Every CI command in a clean copy" bash scripts/ci_local.sh

{ echo; echo "failed_steps=$FAILED"; echo "finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"
# The log is committed, so strip local paths from it.
sed -i.bak -E -e "s#$PWD/##g" -e 's#/(var/folders|private/tmp)/[^ :]*#<temp-dir>#g' "$OUT" && rm -f "$OUT.bak"
exit "$FAILED"
