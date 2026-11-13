#!/usr/bin/env bash
# Rebuilds the local database for the Gate 8 application demo. Deletes only this project's local Docker
# volume. Uses data already built by the earlier gates (acquisition, Gate 6 evidence, Gate 7 decisions);
# it acquires and simulates nothing beyond the deterministic field scenarios.
#
# The difference from the Gate 7 rebuild: decisions load WITHOUT work orders, so no scripted
# demonstration decision is in the database. Every work order in the demo is opened and decided in the
# application by an authenticated person and recorded as HUMAN.
set -euo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV

need() {
  [ -e "$1" ] || { echo "Missing $1. Build it first with: $2" >&2; exit 1; }
}
need data/gold/decision/recommendations.json "make gate7 (or bash scripts/gate7_evidence.sh)"
need data/gold/inspection/inspection_requests.json "make gate6"

docker compose down -v
docker compose up -d --wait postgres
uv run python -m packages.repositories.database
uv run python -m pipelines.normalize.seed
uv run python -m pipelines.normalize.load
uv run python -m pipelines.normalize.petrobras_3w_events
uv run python -m pipelines.synthetic.aether_fault_001
uv run python -m pipelines.synthetic.aether_field
uv run python -m pipelines.reconcile.run
uv run python -m pipelines.inspection.load
uv run python -m pipelines.decision.load --without-work-orders
docker compose exec -T postgres psql -U fieldtwin -d fieldtwin -At \
  -c "SELECT 'alarms', count(*) FROM detector_alarms" \
  -c "SELECT 'recommendations', count(*) FROM recommendations" \
  -c "SELECT 'work_orders', count(*) FROM work_orders WHERE recommendation_id IS NOT NULL" \
  -c "SELECT 'inspection_requests', count(*) FROM inspection_requests"
echo "Application database ready. Next: make app-tokens, then make app-api and make app-web."
