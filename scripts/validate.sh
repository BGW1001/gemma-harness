#!/usr/bin/env bash
set -euo pipefail

echo "Running validation..."
cd "$(dirname "$0")/.."

~/miniconda3/bin/harbor run --agent-import-path harness.agent:GemmaAgent -d terminal-bench/terminal-bench-2 -l 1 || {
    echo "Validation aborted."
    exit 1
}
echo "Validation complete."
