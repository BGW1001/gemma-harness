#!/usr/bin/env bash
# Full Terminal-Bench 2 benchmark on the active backbone.
#
# Runs all 89 tasks × 1 attempt (Pass@1 convention, matches how public
# Terminal-Bench 2 scores are usually reported). Expected wall:
# ~9-12 hours at 6-8 min/task median, longer if the harder tasks
# push to the agent_timeout_multiplier cap.
#
# Usage:
#   bash scripts/full_benchmark.sh                    # 89 tasks × 1 attempt
#   N_ATTEMPTS=3 bash scripts/full_benchmark.sh       # 89 × 3 = 267 trials, ~27-36h
#   AGENT_TIMEOUT_MULTIPLIER=5 bash scripts/full_benchmark.sh   # looser per-task cap
#
# The record_baseline.py step runs after the Harbor job finishes; ledger rows
# carry the same prompt_hash as baseline.sh so EASY_SUBSET + full runs live
# together in runs/ledger.jsonl.

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON=~/miniconda3/bin/python
HARBOR=~/miniconda3/bin/harbor

N_ATTEMPTS=${N_ATTEMPTS:-1}
AGENT_TIMEOUT_MULTIPLIER=${AGENT_TIMEOUT_MULTIPLIER:-5.0}
N_CONCURRENT=${N_CONCURRENT:-1}

JOB_NAME="full_benchmark_$(date +%Y-%m-%d__%H-%M-%S)"
echo "[full] job=$JOB_NAME attempts=$N_ATTEMPTS agent_timeout_multiplier=$AGENT_TIMEOUT_MULTIPLIER concurrent=$N_CONCURRENT"
echo "[full] expected wall: ~9-12h at 1 attempt, ~27-36h at 3 attempts"

"$HARBOR" run \
  --agent-import-path harness.agent:GemmaAgent \
  -d terminal-bench/terminal-bench-2 \
  -k "$N_ATTEMPTS" \
  --agent-timeout-multiplier "$AGENT_TIMEOUT_MULTIPLIER" \
  --n-concurrent "$N_CONCURRENT" \
  --job-name "$JOB_NAME"

"$PYTHON" scripts/record_baseline.py "jobs/$JOB_NAME"
echo "[full] wrote rows to runs/ledger.jsonl"
