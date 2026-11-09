#!/usr/bin/env bash
# Rebuilds the local database from nothing, runs through Gate 5, and records actual output as evidence.
# Deletes only this project's local Docker volume. Needs data from `make acquire`.
set -uo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
OUT=reports/gates/gate_5_execution_log.txt
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

{ echo "Gate 5 execution log"; echo "started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"

step "Fresh database" docker compose down -v
step "Start PostGIS" docker compose up -d --wait postgres
step "Migrate" uv run python -m packages.repositories.database
step "Seed" uv run python -m pipelines.normalize.seed
step "Source schemas" uv run python -m pipelines.profile.source_schemas
step "Load real batches" uv run python -m pipelines.normalize.load
step "3W benchmark events" uv run python -m pipelines.normalize.petrobras_3w_events
step "AETHER-FAULT-001" uv run python -m pipelines.synthetic.aether_fault_001
step "AETHER Field, six scenarios" uv run python -m pipelines.synthetic.aether_field
step "Reconciliation engine" uv run python -m pipelines.reconcile.run
step "Reconciliation again (expect already_run)" uv run python -m pipelines.reconcile.run
step "Canonical validation" uv run python -m pipelines.normalize.validate_canonical
step "Gate 2 reports" uv run python -m pipelines.normalize.reports
step "Reconciliation reports" uv run python -m pipelines.reconcile.reports
step "Scenario report" uv run python -m pipelines.synthetic.report
step "Field reports" uv run python -m pipelines.synthetic.field_reports
step "Field diagrams" env PYTHONPATH=. uv run python scripts/build_field_diagrams.py
step "Remove derived Gate 5 data" rm -rf data/gold/experiments
step "3W label audit" uv run python -m pipelines.experiments.three_w_audit
step "AETHER benchmark data, under the process guard" uv run python -m pipelines.experiments.aether_data
step "3W development folds" uv run python -m pipelines.experiments.three_w_run --stage development
step "AETHER in-regime test" uv run python -m pipelines.experiments.aether_run --stage in_regime
step "3W holdout, rerun" uv run python -m pipelines.experiments.three_w_run --stage holdout
step "AETHER held-out regimes, rerun" uv run python -m pipelines.experiments.aether_run --stage held_out
step "Results match the committed ones" uv run python -m pipelines.experiments.reproducibility
step "Reliability stress" uv run python -m pipelines.experiments.reliability_stress --repeats 30 --workers 4
step "Streaming latency and memory" uv run python -m pipelines.experiments.inference_perf
step "Gate 5 reports" uv run python -m pipelines.experiments.reports
step "Schema document" uv run python -m pipelines.normalize.schema_docs
step "Dump schema" bash -c 'docker compose exec -T postgres pg_dump -U fieldtwin -d fieldtwin --schema-only --no-owner --no-privileges | grep -v "^\\\\\(un\)\?restrict" > db/ddl/schema.sql && wc -l db/ddl/schema.sql'
step "Bronze quality reports" uv run python -m pipelines.profile.cli
step "Raw integrity" uv run python -m pipelines.profile.validate
step "Ruff lint" uv run ruff check .
step "Ruff format" uv run ruff format --check .
step "Mypy" uv run mypy
step "Offline tests" uv run pytest -q
step "Database tests on fixtures" uv run pytest -m "db and not acquired" -o addopts=--strict-markers -q
step "Tests on real data" uv run pytest -m "acquired" -o addopts=--strict-markers -q
step "Every CI command in a clean copy" bash scripts/ci_local.sh

{ echo; echo "failed_steps=$FAILED"; echo "finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"
# The log is committed, so strip local paths from it.
sed -i.bak -E -e "s#$PWD/##g" -e 's#/(var/folders|private/tmp)/[^ :]*#<temp-dir>#g' "$OUT" && rm -f "$OUT.bak"
exit "$FAILED"
