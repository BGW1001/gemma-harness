#!/usr/bin/env bash
# Baseline runner for the "get off zero" target.
#
# Runs gemma-harness against the 3 easy Terminal-Bench 2 tasks, 3 attempts each
# (9 trials total), and appends one ledger row per trial to runs/ledger.jsonl.
#
# Usage:
#   bash scripts/baseline.sh                # full baseline (3 tasks x 3 attempts)
#   SMOKE=1 bash scripts/baseline.sh        # smoke test: 1 task, 1 attempt (fastest)

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON=~/miniconda3/bin/python
HARBOR=~/miniconda3/bin/harbor

# Read the easy subset from Python so it stays single-source-of-truth.
TASKS=$("$PYTHON" -c "from eval.subsets import EASY_SUBSET; print(' '.join(EASY_SUBSET))")

INCLUDE_FLAGS=""
for t in $TASKS; do
  INCLUDE_FLAGS+=" -i $t"
done

N_ATTEMPTS=${N_ATTEMPTS:-3}
if [[ "${SMOKE:-0}" == "1" ]]; then
  INCLUDE_FLAGS="-i fix-git"
  N_ATTEMPTS=1
  echo "[baseline] SMOKE mode: 1 task, 1 attempt"
fi

JOB_NAME="baseline_$(date +%Y-%m-%d__%H-%M-%S)"
echo "[baseline] tasks=$TASKS  attempts=$N_ATTEMPTS  job=$JOB_NAME"

"$HARBOR" run \
  --agent-import-path harness.agent:GemmaAgent \
  -d terminal-bench/terminal-bench-2 \
  $INCLUDE_FLAGS \
  -k "$N_ATTEMPTS" \
  --job-name "$JOB_NAME"

"$PYTHON" scripts/record_baseline.py "jobs/$JOB_NAME"
echo "[baseline] wrote rows to runs/ledger.jsonl"
