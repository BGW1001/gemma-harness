# Gemma Harness

A harness around a local Gemma model (llama.cpp / ROCm) that runs as a [Harbor](https://github.com/laude-institute/harbor) agent against **Terminal-Bench 2**, with an AutoResearch outer loop that iterates on prompts, skills, and policies.

**Goal:** turn a small local model into a useful terminal-task-solving agent by improving the *harness* around it — not the model. Score on Terminal-Bench 2 is the one metric that counts.

For the full picture, see [`docs/OVERVIEW.md`](docs/OVERVIEW.md).

---

## Prerequisites

- Harbor installed in a conda Python env — `~/miniconda3/bin/harbor` is the canonical path in this repo
- Docker running (Harbor spawns task containers)
- A running llama.cpp server exposing an OpenAI-compatible chat endpoint for Gemma (default: `http://localhost:8889/v1`)
- Python ≥3.11

Copy `.env.example` → `.env` and set `GEMMA_ENDPOINT` if your server isn't on the default port.

## Quick start

```bash
# one-shot validation (single trial, for sanity)
bash scripts/validate.sh

# fast smoke (one task, one attempt — ~5–15 min)
SMOKE=1 bash scripts/baseline.sh

# full baseline (EASY_SUBSET × 3 attempts — ~30–90 min)
bash scripts/baseline.sh
```

After a baseline run, inspect the ledger:

```bash
tail -n 9 runs/ledger.jsonl | python -m json.tool
```

## Layout

```
prompts/     # system prompt (editable — AutoResearch mutates)
skills/      # named playbooks, one file each (editable)
policies/    # behavioural rules, one file each (editable)
config.yaml  # temperature, max_turns, etc. (editable)
prompts.py   # composes SYSTEM_PROMPT from the markdown above

harness/     # Harbor BaseAgent integration (locked)
eval/        # scoring + task subsets (locked)
optimizer/   # AutoResearch loop (locked, not yet wired)

scripts/
  validate.sh         # single-trial smoke
  baseline.sh         # EASY_SUBSET × N attempts
  record_baseline.py  # parse job dir → append ledger rows

jobs/                 # per-trial trajectories + scores (Harbor output)
runs/ledger.jsonl     # append-only row per scored trial
docs/                 # OVERVIEW.md + daily progress notes
```

**Editable vs. locked** is load-bearing: the optimizer searches the editable surface; the locked surface is the plumbing that must be stable for scores to be meaningful. Changes to `harness/*`, `eval/*`, or `optimizer/*` require an explicit handoff note.

## The iteration loop

1. Pick one change from MEMORY.md / a named hypothesis
2. Apply it to the editable surface
3. Confirm the new `prompt_hash` differs from baseline
4. `bash scripts/baseline.sh` → EASY_SUBSET × 3 attempts
5. `python scripts/record_baseline.py jobs/<job_name>`
6. Inspect mean reward, per-task reward, failure-tag distribution
7. Append a dated entry to `~/.openclaw/workspace/agents/gemma-agent/memory/learnings.md`
8. Confirmed × 2 iterations → promote to `MEMORY.md`. Underperformed → add to `DONT_DO.md` and revert.

Every ledger row carries a `prompt_hash` (sha256[:16] of the composed `SYSTEM_PROMPT`) and a `failure_tag` (`success | partial | turn_exhaustion | graceful_giveup | tool_error_cascade | unknown_zero`). These two fields make the ledger analyzable — without them, scores have no attribution.

## Target subset

`eval/subsets.py` defines `EASY_SUBSET` — three procedural Terminal-Bench 2 tasks chosen to be within Gemma's plausible ceiling:

- `fix-git` (7-line reference solution)
- `openssl-selfsigned-cert` (~98-line procedural recipe)
- `git-leak-recovery` (well-scoped secret scrub)

"Not zero" on EASY_SUBSET is the current gate. Tuning on tasks beyond the model's ceiling is noise.

## Current state

- Harbor + Terminal-Bench 2 proven (oracle agent scores 1.000)
- `gemma-harness` runs as a real Harbor BaseAgent
- Pre-change baseline: `prompt_hash 04b78e2f` → 0.00 on `make-mips-interpreter` (task beyond model ceiling)
- Post-change baseline under the new composed prompt: **not yet measured** — next action is `bash scripts/baseline.sh`

See `docs/PROGRESS_2026-04-20.md` for today's detailed progress and `docs/OVERVIEW.md` for the end-to-end reference.

## Related

- OpenClaw agent folder: `~/.openclaw/workspace/agents/gemma-agent/` (identity, rules, memory, learnings, anti-patterns)
- Handoffs: `~/.openclaw/workspace/handoffs/gemma-harness-*.md`
