#!/usr/bin/env bash
# One command from a clean checkout to the running FieldTwin demo on http://127.0.0.1:8000.
#
#   bash scripts/run_demo.sh              # build everything, then serve until Ctrl-C
#   bash scripts/run_demo.sh --no-serve   # build everything and stop
#
# Needs: uv, Node 20 or later with npm, and Docker (for local PostGIS). It downloads the public sources
# on first run (about 1.7 GB) and reuses completed raw batches afterwards. It deletes only this
# project's local Docker volume. It creates no cloud resource and makes no paid API call.
#
# Every step is a pipeline earlier gates already validated; nothing here is specific to the demo
# except loading decisions without work orders, so every demo decision is made by a signed-in person.
set -euo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
SERVE=1
[ "${1:-}" = "--no-serve" ] && SERVE=0
PORT="${FIELDTWIN_DEMO_PORT:-8000}"

say() { printf '\n== %s\n' "$*"; }
need() { command -v "$1" > /dev/null || { echo "Missing $1. $2" >&2; exit 1; }; }
need uv "Install it from https://docs.astral.sh/uv/."
need npm "Install Node 20 or later."
need docker "Install Docker and start it."
docker info > /dev/null 2>&1 || { echo "Docker is installed but not running." >&2; exit 1; }

say "Dependencies"
uv sync --frozen
npm ci --no-audit --no-fund

say "Public sources (reuses completed batches)"
uv run python -m pipelines.acquire.cli nm_ocd
uv run python -m pipelines.acquire.cli petrobras_3w
uv run python -m pipelines.profile.cli
uv run python -m pipelines.profile.validate

say "Fresh database and the fictional field"
docker compose down -v
docker compose up -d --wait postgres
uv run python -m packages.repositories.database
uv run python -m pipelines.normalize.seed
uv run python -m pipelines.normalize.load
uv run python -m pipelines.normalize.petrobras_3w_events
uv run python -m pipelines.synthetic.aether_fault_001
uv run python -m pipelines.synthetic.aether_field
uv run python -m pipelines.reconcile.run

MODEL=data/gold/experiments/models/aether_hist_gradient_boosting.joblib
EXPECTED=$(python3 -c "import json; print(json.load(open('reports/experiments/results/aether_held_out.json'))['artifacts']['hist_gradient_boosting']['sha256'])")
if [ -f "$MODEL" ] && [ "$(shasum -a 256 "$MODEL" | cut -d' ' -f1)" = "$EXPECTED" ]; then
  say "Gate 5 detector: present, checksum matches the committed results"
else
  # The selected model is saved by the held-out stage. In a rebuild that stage reproduces a recorded
  # evaluation; the committed results file must come out byte-identical, or the demo stops.
  say "Gate 5 detector: rebuilding the synthetic dataset and both AETHER stages (several minutes)"
  BEFORE=$(mktemp -d)
  cp reports/experiments/results/aether_in_regime.json reports/experiments/results/aether_held_out.json "$BEFORE/"
  uv run python -m pipelines.experiments.aether_data
  uv run python -m pipelines.experiments.run_stage aether-in-regime -- pipelines.experiments.aether_run --stage in_regime
  uv run python -m pipelines.experiments.run_stage aether-held-out -- pipelines.experiments.aether_run --stage held_out
  uv run python scripts/verify_gate5_rebuild.py "$BEFORE" reports/experiments/results
  rm -rf "$BEFORE"
  ACTUAL=$(shasum -a 256 "$MODEL" | cut -d' ' -f1)
  [ "$ACTUAL" = "$EXPECTED" ] || { echo "Rebuilt detector $ACTUAL doesn't match the committed $EXPECTED." >&2; exit 1; }
  echo "Rebuilt detector matches the committed checksum $EXPECTED."
fi

say "Aerial evidence (Gate 6; reuses completed batches)"
uv run python -m pipelines.acquire.cli carbon_mapper
uv run python -m pipelines.inspection.associate
uv run python -m pipelines.acquire.cli naip
uv run python -m pipelines.inspection.verify
uv run python -m pipelines.inspection.requests
uv run python -m pipelines.inspection.evidence
uv run python -m pipelines.inspection.load

say "Decisions (Gate 7), loaded without work orders"
uv run python -m pipelines.decision.run
uv run python -m pipelines.decision.load --without-work-orders

say "Web app"
npm --workspace apps/web run build

[ -f .env.app ] || uv run python scripts/app_tokens.py > /dev/null
say "Ready"
echo "Sign-in tokens, one per role (from .env.app; local only):"
cut -d= -f2- .env.app | tr ',' '\n' | awk -F: '{printf "  %-24s %-18s %s\n", $2, $1, $3}'
if [ "$SERVE" = 0 ]; then
  echo "Built. Serve with: bash scripts/run_demo.sh (or make app-api and make app-web)."
  exit 0
fi
echo "Open http://127.0.0.1:$PORT  (Ctrl-C stops the server; the database keeps running: make db-down)"
set -a
. ./.env.app
set +a
export FIELDTWIN_WEB_DIST=apps/web/dist PYTHONPATH=.:apps/api/src
exec uv run uvicorn fieldtwin_api.main:app --host 127.0.0.1 --port "$PORT"
