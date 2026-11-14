#!/usr/bin/env bash
# Gate 8 evidence: rebuild the demo database, run a live smoke test against the API, build and test
# the web app, then leave a clean demo database. Deletes only this project's local Docker volume.
# Needs the data built by Gates 1 to 7 (it acquires and recomputes no experiment).
set -uo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
OUT=reports/gates/gate_8_execution_log.txt
PORT=8765
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

{ echo "Gate 8 execution log"; echo "started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"

# Throwaway tokens for this run only; never written to disk or the log.
TOKENS="smoke-viewer:VIEWER:$(openssl rand -hex 24),smoke-operator:OPERATOR:$(openssl rand -hex 24),smoke-supervisor:MAINTENANCE_SUPERVISOR:$(openssl rand -hex 24)"

step "Demo database" bash scripts/app_db.sh
FIELDTWIN_API_TOKENS="$TOKENS" PYTHONPATH=.:apps/api/src uv run uvicorn fieldtwin_api.main:app --host 127.0.0.1 --port "$PORT" > /dev/null 2>&1 &
API_PID=$!
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/health" > /dev/null && break; sleep 1; done
# Exported, not passed on the command line, so the logged command never contains a token.
export FIELDTWIN_SMOKE_TOKENS="$TOKENS"
step "Live API smoke test" uv run python scripts/gate8_smoke.py "http://127.0.0.1:$PORT"
unset FIELDTWIN_SMOKE_TOKENS
kill "$API_PID" 2> /dev/null
wait "$API_PID" 2> /dev/null
step "Clean demo database again" bash scripts/app_db.sh
step "Ruff lint" uv run ruff check .
step "Ruff format" uv run ruff format --check .
step "Mypy" uv run mypy
step "API tests, offline" uv run pytest apps/api/tests -q
step "API tests, database" uv run pytest apps/api/tests -m db -o addopts=--strict-markers -q
step "Install web dependencies" npm ci --no-audit --no-fund
step "Audit production web dependencies" npm audit --omit=dev --audit-level=high
step "Web type check" npm --workspace apps/web run typecheck
step "Web tests" npm --workspace apps/web run test
step "Web build" npm --workspace apps/web run build
step "Offline tests" uv run pytest -q
step "Database tests on fixtures" uv run pytest -m "db and not acquired" -o addopts=--strict-markers -q
step "Every CI command in a clean copy" bash scripts/ci_local.sh

{ echo; echo "failed_steps=$FAILED"; echo "finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"
exit "$FAILED"
