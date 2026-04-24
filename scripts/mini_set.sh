#!/usr/bin/env bash
# Run the 20-task MINI_SET for AutoResearch inner-loop evaluation.
# ~2-3h wall time at agent_timeout_multiplier=5.0.
#
# Usage:
#   bash scripts/mini_set.sh
#   N_ATTEMPTS=2 bash scripts/mini_set.sh                # Pass@2
#   AGENT_TIMEOUT_MULTIPLIER=3.0 bash scripts/mini_set.sh # tighter cap

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=~/miniconda3/bin/python
HARBOR=~/miniconda3/bin/harbor

TASKS=$("$PYTHON" -c "from eval.subsets import MINI_SET; print(' '.join(MINI_SET))")
INCLUDE_FLAGS=""
for t in $TASKS; do INCLUDE_FLAGS+=" -i $t"; done

N_ATTEMPTS=${N_ATTEMPTS:-1}
AGENT_TIMEOUT_MULTIPLIER=${AGENT_TIMEOUT_MULTIPLIER:-5.0}
N_CONCURRENT=${N_CONCURRENT:-1}

JOB_NAME="mini_set_$(date +%Y-%m-%d__%H-%M-%S)"
echo "[mini_set] job=$JOB_NAME  attempts=$N_ATTEMPTS  cap_mult=$AGENT_TIMEOUT_MULTIPLIER"

"$HARBOR" run \
  --agent-import-path harness.agent:GemmaAgent \
  -d terminal-bench/terminal-bench-2 \
  $INCLUDE_FLAGS \
  -k "$N_ATTEMPTS" \
  --agent-timeout-multiplier "$AGENT_TIMEOUT_MULTIPLIER" \
  --n-concurrent "$N_CONCURRENT" \
  --job-name "$JOB_NAME"

"$PYTHON" scripts/record_baseline.py "jobs/$JOB_NAME"
echo "[mini_set] wrote rows to runs/ledger.jsonl"
