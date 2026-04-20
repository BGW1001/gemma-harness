# Gemma Harness Project — Handoff Brief

## Goal

Build a harness framework around a local Gemma model (running on llama.cpp/ROCm) and use a Karpathy-style AutoResearch outer loop to optimize the harness against Terminal-Bench 2. Ultimate target: make the local Gemma capable enough to run OpenClaw-style agentic workloads.

## Architectural decisions (locked)

### Model serving (existing, do not modify)

- Bespoke llama.cpp build with ROCm (AMD GPU)
- Gemma model, 256K context, ~40 t/s
- Port 8889: raw OpenAI-compatible endpoint — **harness targets this**
- Port 8891: wrapper with chat UI — harness ignores this
- Native OpenAI `tool_calls` confirmed working on 8889 (tested)
- Concurrent requests confirmed working (tested with 2 parallel curls)

### Harness target

- Terminal-Bench 2 (89 tasks) as primary benchmark
- Inner eval: 10-task subset for fast iteration
- Validation: full 89 tasks, run only on promising candidates
- Uses Harbor framework / Terminus 2 harness as integration point

### Outer loop

- Optimizer LLM: Gemini API (cheapest for iterative proposals)
- Fallback: swap to OpenAI/Anthropic API if proposal quality becomes bottleneck
- Pattern: Karpathy AutoResearch three primitives — editable asset, scalar metric, time-boxed cycle

### Phase 1 editable surface

- `prompts.py` — system/plan/reflect prompts
- `config.yaml` — turn limits, temperature, best-of-N, max tokens
- `harness/*` is LOCKED in Phase 1

### Phase 2 (later, after baseline stable)

- Unlock `harness.py` itself as editable
- Add syntax check + smoke test before scoring proposed patches

### Infrastructure

- Repo lives inside WSL Linux filesystem (NOT `/mnt/c`) due to bind-mount issues
- Docker Desktop with WSL2 backend for Terminal-Bench task sandboxes
- Expect some mount quirks; "recreate container" is legitimate recovery

## Repo layout

```
gemma-harness/
├── README.md
├── program.md                    # Karpathy-style spec
├── pyproject.toml
├── .env.example                  # GEMINI_API_KEY, GEMMA_ENDPOINT
├── .gitignore
├── harness/                      # LOCKED Phase 1
│   ├── __init__.py
│   ├── harness.py                # agent loop
│   ├── tools.py                  # tool schemas + impls
│   ├── client.py                 # wraps :8889
│   └── context.py                # scratchpad / pruning
├── prompts.py                    # EDITABLE
├── config.yaml                   # EDITABLE
├── eval/
│   ├── terminal_bench.py
│   ├── subsets.py
│   └── scoring.py
├── optimizer/
│   ├── propose.py                # Gemini API calls
│   ├── archive.py                # runs/ ledger
│   ├── apply.py                  # apply + validate patch
│   └── loop.py                   # outer loop entry
├── runs/                         # git-tracked experiment log
└── scripts/
    ├── baseline.sh
    ├── overnight.sh
    └── validate.sh
```

## Reference implementations

### `harness/client.py`

```python
import os
from openai import OpenAI

_client = OpenAI(
    base_url=os.environ.get("GEMMA_ENDPOINT", "http://localhost:8889/v1"),
    api_key="sk-ignored",
)

def chat(messages, tools=None, **kwargs):
    return _client.chat.completions.create(
        model="gemma", messages=messages, tools=tools, **kwargs,
    )
```

### `harness/harness.py`

```python
import json
from harness.client import chat
from harness.tools import TOOL_SCHEMAS, execute
from prompts import SYSTEM_PROMPT

def run(task, cwd, config):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    for turn in range(config["max_turns"]):
        resp = chat(
            messages, tools=TOOL_SCHEMAS,
            temperature=config["temperature"],
            max_tokens=config["max_tokens_per_call"],
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_unset=True))

        if resp.choices[0].finish_reason == "stop":
            return {"status": "done", "turns": turn, "trace": messages}

        for tc in (msg.tool_calls or []):
            args = json.loads(tc.function.arguments)
            result = execute(tc.function.name, args, cwd)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return {"status": "turn_limit", "turns": config["max_turns"], "trace": messages}
```

## Runs ledger schema (lock this now)

Each experiment writes one JSON file to `runs/`:

```json
{
  "experiment_id": "0001",
  "timestamp": "...",
  "config_diff": "...",
  "prompts_diff": "...",
  "inner_score": 0.3,
  "worst_traces": ["...", "..."],
  "wall_time_sec": 1800,
  "gemini_hypothesis": "...",
  "parent_experiment": "0000"
}
```

## Build sequence

1. Scaffold all files per layout above. All stubs compile/import cleanly.
2. Implement `tools.py` — bash first, then file_view, file_edit, grep. Test each against :8889 with manual curl loops.
3. Get `harness.run()` solving one hand-written trivial task end-to-end ("write hello world to /tmp/out.txt"). Proves full tool-call loop with Gemma.
4. Wire `eval/terminal_bench.py` to Harbor. Pick 10 inner-eval tasks: mix of easy/medium, avoid hard tasks for inner loop.
5. Run baseline 3x, record variance. If variance > plausible improvements, fix before optimizing.
6. Only then start Phase 1 optimizer loop.

## Guardrails / known risks

- **Reward hacking:** Terminal-Bench tasks contain canary strings and pytests. Harness should not be able to read the test files.
- **Overfitting inner subset:** rotate tasks, hold out 40-50 validation-only.
- **Goodhart:** watch for mutations that help inner 10 but hurt full 89.
- **Throughput reality:** ~20-40 min/task at 40 t/s means ~4-8 experiments/day, not Karpathy's 100/day. Optimizer must use priors from known agent-scaffolding literature, not random exploration.
- **Docker bind-mount quirks on WSL2:** workdirs inside Linux FS only.

## `program.md` content

```markdown
# Harness Optimization

## Objective
Maximize pass rate on Terminal-Bench 2 inner eval (10 tasks).
Metric: pass_rate ∈ [0.0, 1.0], higher is better.

## Editable (Phase 1)
- prompts.py
- config.yaml

## Locked
- harness/*

## Constraints
- max_turns ∈ [10, 200]
- temperature ∈ [0.0, 1.5]
- prompts must be non-empty strings
- config must parse as valid YAML

## Search hints
Known-helpful patterns: explicit planning, post-tool reflection,
concrete tool descriptions, best-of-N on hard turns, context pruning
between turns.

## Stopping
- 100 experiments, OR
- no improvement for 20 consecutive experiments
```

## First task for Claude Code

1. Create the repo directory structure above.
2. Write all stub files with the reference implementations shown.
3. Make sure `python -c "from harness.harness import run"` works.
4. Initialize git, create `.gitignore` (venv, `.env`, `__pycache__`, `runs/*.json` except `.gitkeep`).
5. Create empty GitHub repo via `gh repo create` and push.
6. **Stop there.** Do not implement tools, eval, or optimizer yet — that's step 2 of the build sequence and worth a separate session.
