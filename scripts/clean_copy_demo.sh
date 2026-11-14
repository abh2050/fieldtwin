#!/usr/bin/env bash
# Proves the demo has no hidden manual steps: runs scripts/run_demo.sh in a clean copy that holds only
# the tracked files: no downloaded or derived data, no model, no database, and no node_modules. It
# downloads the public sources again (about 1.7 GB), so it takes a while. Then it serves the result,
# runs the live smoke test, and checks that the rebuild changed no committed file.
#
# The copy uses port 55432, so this project's own database container is stopped (not deleted) for
# the run and started again afterwards. The copy's database volume is deleted at the end.
set -uo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
REPO="$PWD"
WORK="$(mktemp -d)/fieldtwin-clean"
PORT=8766
mkdir -p "$WORK"
cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2> /dev/null
  (cd "$WORK" && docker compose down -v > /dev/null 2>&1)
  rm -rf "$(dirname "$WORK")"
  (cd "$REPO" && docker compose up -d --wait postgres > /dev/null 2>&1)
}
trap cleanup EXIT

git ls-files -co --exclude-standard | rsync -a --files-from=- ./ "$WORK/"
cd "$WORK" || exit 1
git init -q . && git add -A && git -c user.name=clean -c user.email=clean@localhost commit -qm clean
echo "clean_copy_tracked_files=$(git ls-files | wc -l | tr -d ' ')"
echo "untracked_data_files_present=$(git ls-files -o --exclude-standard data | wc -l | tr -d ' ')"
echo "raw_batches_present=$(find data/raw -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
echo "node_modules_present=$([ -d node_modules ] && echo yes || echo no)"

(cd "$REPO" && docker compose stop postgres > /dev/null 2>&1)
started=$(date +%s)
bash scripts/run_demo.sh --no-serve
code=$?
echo "run_demo_exit=$code seconds=$(( $(date +%s) - started ))"
[ "$code" -eq 0 ] || exit 1

# A fresh download and a rerun legitimately rewrite run records: manifests, profiles of a newer
# upstream release, validation timestamps, the attempt ledger, and generation timings. Recorded
# results must not change.
echo "committed_files_changed_by_rebuild:"
git status --porcelain --untracked-files=no
RESULTS='reports/(experiments/results/(aether_(in_regime|held_out)|3w_[a-z_]+|inference_performance|reliability_stress)\.json|decision/results/|inspection/results/|diagnostics/)'
changed=$(git status --porcelain --untracked-files=no | grep -cE " $RESULTS" || true)
echo "recorded_result_files_changed=$changed"

TOKENS=$(cut -d= -f2- .env.app)
FIELDTWIN_API_TOKENS="$TOKENS" FIELDTWIN_WEB_DIST=apps/web/dist PYTHONPATH=.:apps/api/src \
  uv run uvicorn fieldtwin_api.main:app --host 127.0.0.1 --port "$PORT" > /dev/null 2>&1 &
API_PID=$!
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/health" > /dev/null && break; sleep 1; done
echo "web_app_index_served=$(curl -s "http://127.0.0.1:$PORT/maintenance" | grep -c '<div id="root">')"
export FIELDTWIN_SMOKE_TOKENS="$TOKENS"
uv run python "$REPO/scripts/gate8_smoke.py" "http://127.0.0.1:$PORT" | python3 -c "import json,sys; d=json.load(sys.stdin); print('smoke_reads_ok=%d/%d' % (sum(v==200 for v in d['reads'].values()), len(d['reads']))); print('smoke_workflow_steps=%d' % len(d['workflow'])); print('smoke_failures=%s' % d['failures']); sys.exit(1 if d['failures'] else 0)"
smoke=$?
[ "$changed" = "0" ] && [ "$smoke" -eq 0 ]
