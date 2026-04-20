#!/usr/bin/env bash
set -euo pipefail

echo "Running 3x baseline..."
cd "$(dirname "$0")/.."

for i in {1..3}; do
    echo "--- Baseline Run $i ---"
    ~/miniconda3/bin/harbor run --agent-import-path harness.agent:GemmaAgent -d tau/terminal-bench -l 3 || {
        echo "Run $i aborted due to error."
        echo "Cannot complete 3x baseline."
        exit 1
    }
done
echo "Baseline 3x complete."
