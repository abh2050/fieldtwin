#!/usr/bin/env bash
# Rebuilds the local database from nothing, runs every Gate 6 and Gate 7 stage, and records actual output.
# Deletes only this project's local Docker volume. Needs data from `make acquire` and the Gate 6
# acquisitions; those reuse their completed batches, so no new download happens unless one is missing.
# Gate 5 experiments are not rerun: Gates 6 and 7 change none of their code or inputs. Gate 7 reads the
# committed Gate 5 model bundle, whose checksum is verified on load.
set -uo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
OUT=reports/gates/gate_7_execution_log.txt
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

{ echo "Gate 7 execution log"; echo "started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"

step "Fresh database" docker compose down -v
step "Start PostGIS" docker compose up -d --wait postgres
step "Migrate" uv run python -m packages.repositories.database
step "Seed" uv run python -m pipelines.normalize.seed
step "Load real batches" uv run python -m pipelines.normalize.load
step "3W benchmark events" uv run python -m pipelines.normalize.petrobras_3w_events
step "AETHER-FAULT-001" uv run python -m pipelines.synthetic.aether_fault_001
step "AETHER Field, six scenarios" uv run python -m pipelines.synthetic.aether_field
step "Reconciliation engine" uv run python -m pipelines.reconcile.run
step "Reconciliation again (expect already_run)" uv run python -m pipelines.reconcile.run
step "Canonical validation" uv run python -m pipelines.normalize.validate_canonical
step "Carbon Mapper (reuses the completed batch)" uv run python -m pipelines.acquire.cli carbon_mapper
step "Remove derived Gate 6 data" rm -rf data/silver/inspection data/gold/inspection/evidence.html data/gold/inspection/review_queue.html data/gold/inspection/chips data/gold/inspection/evidence_cards.json data/gold/inspection/inspection_requests.json
step "Plume association and coverage" uv run python -m pipelines.inspection.associate
step "NAIP (reuses the completed batch for the same selection)" uv run python -m pipelines.acquire.cli naip
step "Raw integrity of the aerial batches" uv run python -m pipelines.inspection.verify
step "Raw integrity of the Gate 1 batches" uv run python -m pipelines.profile.validate
step "Inspection requests for fictional assets" uv run python -m pipelines.inspection.requests
step "Evidence cards and review pages" uv run python -m pipelines.inspection.evidence
step "Load aerial evidence" uv run python -m pipelines.inspection.load
step "Load again (expect no new rows)" uv run python -m pipelines.inspection.load
step "Database row counts" bash -c "docker compose exec -T postgres psql -U fieldtwin -d fieldtwin -At -c \"SELECT relationship_type, verification_status, count(*) FROM asset_observation_links WHERE method_version LIKE 'gate6%' GROUP BY 1, 2 ORDER BY 1\" -c \"SELECT source_system_id, observation_type, count(*) FROM observations WHERE source_system_id IN ('carbon_mapper', 'naip') GROUP BY 1, 2 ORDER BY 1\" -c 'SELECT count(*) AS inspection_requests FROM inspection_requests' -c 'SELECT count(*) AS reviews FROM inspection_review_events'"
step "Gate 6 reports" uv run python -m pipelines.inspection.reports
step "Remove derived Gate 7 data" rm -rf data/gold/decision
step "Decisions: alarm replay, recommendations, work orders" uv run python -m pipelines.decision.run --refresh
step "Load decisions" uv run python -m pipelines.decision.load
step "Load decisions again (expect no new rows)" uv run python -m pipelines.decision.load
step "Decision row counts" bash -c "docker compose exec -T postgres psql -U fieldtwin -d fieldtwin -At -c 'SELECT count(*) AS alarms FROM detector_alarms' -c 'SELECT action, count(*) FROM recommendations GROUP BY 1 ORDER BY 1' -c 'SELECT status, priority_band, count(*) FROM work_orders WHERE recommendation_id IS NOT NULL GROUP BY 1, 2' -c 'SELECT decision, actor_kind, count(*) FROM work_order_transitions GROUP BY 1, 2 ORDER BY 1, 2' -c \"SELECT count(*) AS transitions_without_audit FROM work_order_transitions t WHERE NOT EXISTS (SELECT 1 FROM audit_events e WHERE e.correlation_id = 'transition:' || t.transition_id)\""
step "Modeled economics" uv run python -m pipelines.decision.economics
step "Evidence audit" uv run python -m pipelines.decision.audit
step "Gate 7 reports" uv run python -m pipelines.decision.reports
step "Diagrams" env PYTHONPATH=. uv run python scripts/build_field_diagrams.py
step "Schema document" uv run python -m pipelines.normalize.schema_docs
step "Dump schema" bash -c 'docker compose exec -T postgres pg_dump -U fieldtwin -d fieldtwin --schema-only --no-owner --no-privileges | grep -v "^\\\\\(un\)\?restrict" > db/ddl/schema.sql && wc -l db/ddl/schema.sql'
step "Ruff lint" uv run ruff check .
step "Ruff format" uv run ruff format --check .
step "Mypy" uv run mypy
step "Offline tests" uv run pytest -q
step "Database tests on fixtures" uv run pytest -m "db and not acquired" -o addopts=--strict-markers -q
step "Tests on real data" uv run pytest -m "acquired" -o addopts=--strict-markers -q
step "Live endpoint checks" uv run pytest -m live -o addopts=--strict-markers -q
step "Every CI command in a clean copy" bash scripts/ci_local.sh

{ echo; echo "failed_steps=$FAILED"; echo "finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"
sed -i.bak -E -e "s#$PWD/##g" -e 's#/(var/folders|private/tmp)/[^ :]*#<temp-dir>#g' "$OUT" && rm -f "$OUT.bak"
exit "$FAILED"
