#!/usr/bin/env bash
# Gate 10 evidence: regenerate the portfolio from the committed results, measure costs, run every
# check, and leave a clean demo database. The clean-checkout demo (scripts/clean_copy_demo.sh)
# downloads about 1.7 GB, so it runs separately; pass its log to have it recorded and measured:
#
#   bash scripts/clean_copy_demo.sh > /tmp/clean_copy.log 2>&1
#   bash scripts/gate10_evidence.sh /tmp/clean_copy.log
set -uo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
OUT=reports/gates/gate_10_execution_log.txt
CLEAN=reports/gates/gate_10_clean_copy_log.txt
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

{ echo "Gate 10 execution log"; echo "started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"

if [ -n "${1:-}" ]; then
  # Keep the clean-copy record without its throwaway tokens or progress noise.
  grep -v '"production scan progress"' "$1" \
    | sed -E -e 's#/(var/folders|private/tmp)/[^ :]*#<temp-dir>#g' \
             -e 's/^(  (VIEWER|OPERATOR|MAINTENANCE_SUPERVISOR) +[a-z-]+ +)[A-Za-z0-9_-]{20,}$/\1<redacted>/' > "$CLEAN"
  step "Clean-checkout demo result" grep -E '^(clean_copy|untracked_data|raw_batches|node_modules|run_demo_exit|committed_files|recorded_result|web_app|smoke_|Rebuilt detector)' "$CLEAN"
fi
step "Demo database" bash scripts/app_db.sh
step "Evaluation summary from committed results" uv run python scripts/portfolio_summary.py
step "Summary unchanged by regeneration" git diff --exit-code -- reports/portfolio/evaluation_summary.md
step "Measured costs" uv run python scripts/measure_costs.py ${1:+--demo-log "$CLEAN"}
step "Bandit security scan (findings triaged in docs/security_review.md)" uvx bandit==1.8.0 -q -r apps/api/src packages pipelines scripts --severity-level medium --confidence-level medium -f txt --exit-zero
step "Ruff lint" uv run ruff check .
step "Ruff format" uv run ruff format --check .
step "Mypy" uv run mypy
step "Offline tests" uv run pytest -q
step "Database tests on fixtures" uv run pytest -m "db and not acquired" -o addopts=--strict-markers -q
step "Install web dependencies" npm ci --no-audit --no-fund
step "Web tests" npm --workspace apps/web run test
step "Web build" npm --workspace apps/web run build
step "Every CI command in a clean copy" bash scripts/ci_local.sh

{ echo; echo "failed_steps=$FAILED"; echo "finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT"
exit "$FAILED"
