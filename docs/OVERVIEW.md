# Gemma Harness — Overview

Canonical reference for the project end-to-end. Start here; drill into progress notes and handoffs for point-in-time state.

Last updated: 2026-04-21.

**Reading convention used throughout this doc:**

- **Validated** — implemented *and* demonstrated to work with evidence in the repo
- **Built** — implemented but not yet empirically validated
- **Intended** — designed / next-step architecture, not yet built

Each section flags which of these it is describing. If a claim is not flagged, assume the weakest applicable category (usually "built").

---

## 1. Goal

Turn a local Gemma model (llama.cpp / ROCm) into a useful terminal-task-solving agent by iterating the **harness around the model**, not by retraining the model itself.

Success is measured by **mean reward on Terminal-Bench 2** via Harbor. The iteration loop is **AutoResearch** (Karpathy-style): a small set of editable artifacts is mutated by the optimizer, scored, and the winners promoted.

Two non-goals to keep clear:

- **Not** fine-tuning or otherwise training Gemma
- **Not** replacing the model with a larger one to cheat the benchmark

The product of this project is a **harness pattern** that makes a small local model useful, and whatever durable rules fall out along the way.

---

## 2. How it runs

```
                 Harbor (orchestrator)
                        │
                        ▼
        Terminal-Bench 2 task container (Docker)
                        │
                        ▼
          GemmaAgent (harness/agent.py)   ◄──── editable artifact surface
                        │                            (prompts, skills, policies)
                        ▼
          llama.cpp server (local Gemma)
```

Harbor runs the task container, invokes `GemmaAgent`, and scores the produced artifacts via the task's verifier. `GemmaAgent` runs an inner loop that feeds the composed `SYSTEM_PROMPT` + the instruction to Gemma, executes the tool calls Gemma emits against the task container, and returns when either the task completes or the turn budget is exhausted.

AutoResearch wraps that loop: mutate the artifacts, re-score, keep or discard.

---

## 3. Repo layout

```
gemma-harness/
├── prompts/                # EDITABLE — AutoResearch mutates
│   └── system.md           # Operating contract for the agent
├── skills/                 # EDITABLE — named playbooks, one file each
│   └── plan.md
├── policies/               # EDITABLE — behavioural rules, one file each
│   ├── stop-loops.md
│   └── submit-early.md
├── config.yaml             # EDITABLE — temperature, max_turns, etc.
├── prompts.py              # Composes SYSTEM_PROMPT from the markdown above
│
├── harness/                # LOCKED — Harbor integration plumbing
│   ├── agent.py            # GemmaAgent(BaseAgent)
│   ├── harness.py          # run_agent inner loop
│   ├── client.py           # llama.cpp OpenAI-compat chat client
│   ├── tools.py            # bash, file_view, file_edit, grep tool schemas
│   └── context.py
│
├── eval/                   # LOCKED — scoring + task subsets
│   ├── scoring.py
│   └── subsets.py          # EASY_SUBSET, etc.
├── optimizer/              # LOCKED — AutoResearch loop (to be wired)
│   ├── loop.py, propose.py, apply.py, archive.py
│
├── scripts/
│   ├── baseline.sh         # run EASY_SUBSET × N attempts via Harbor
│   ├── record_baseline.py  # parse Harbor job dir, append ledger rows
│   └── validate.sh         # smoke validation (single trial)
│
├── jobs/                   # Harbor job outputs (per-trial trajectories + scores)
├── runs/
│   └── ledger.jsonl        # Append-only row per scored trial
└── docs/
    ├── OVERVIEW.md         # this file
    ├── PROGRESS_*.md       # daily progress notes
    └── ...
```

### Editable vs. locked

The split is deliberate and load-bearing.

**Editable surface** is what AutoResearch searches over. It is small by design — small means faster convergence, clearer attribution, less chance the optimizer wanders somewhere destructive. A single file per skill and per policy means the optimizer can add/remove/edit atomically.

**Locked surface** is the plumbing that must be stable for any score to be meaningful. Changes to `harness/*`, `eval/*`, or `optimizer/*` require an explicit handoff note explaining why. The intent is not that they are never changed; it is that they never change quietly.

---

## 4. The agent loop

**Status: validated.** The loop below has been exercised end-to-end against Terminal-Bench 2, most recently on the MIPS trial (job `2026-04-20__12-34-11`).

In `harness/harness.py`, `run_agent` does the following for each trial:

1. Seed `messages` with the composed `SYSTEM_PROMPT` (system role) and the task instruction (user role).
2. For up to `config.max_turns`:
   - Call the llama.cpp chat endpoint with the current `messages` and tool schemas
   - If `finish_reason == "stop"` → **the inner loop ends and returns control to Harbor.** This is *not* task success. Task success is determined only by the Harbor verifier reward in step 3.
   - Strip `reasoning_content` from the assistant message (llama.cpp rejects history that carries it — a server-side quirk with thinking mode), then append the message
   - Execute every emitted tool call against the Harbor task environment and append the result as a `tool` message
3. On turn limit, return `status="turn_limit"`.

Harbor then runs the task's verifier over the container state and emits a reward in `[0, 1]`. **That reward is the only signal of task success.**

### Tools Gemma has

From `harness/tools.py`:

- `bash(cmd)` — run a bash command in the task working directory
- `file_view(path)` — cat a file
- `file_edit(path, old_text, new_text)` — uniqueness-checked in-place edit
- `grep(pattern, path?)` — recursive regex search

Four orthogonal tools. Keeping this set minimal is intentional; each tool description is a few bytes of context the model pays for every turn.

---

## 5. The editable-artifact surface in detail

**Status: built; not yet empirically validated.** The surface below is implemented as the intended search/control layer for AutoResearch. Whether these specific artifacts change outcomes on Terminal-Bench 2 is not yet measured. The next baseline run under the new composed `prompt_hash` is the first test of whether the surface produces any signal at all. Until that run completes and is logged in `runs/ledger.jsonl`, treat this section as a design contract, not a validated lever.

### `prompts/system.md`

The operating contract. Covers:

- **Output contract** — every assistant message must have visible reasoning in `content` before the tool call. An empty `content` makes the run malformed.
- **Per-turn format** — Observation, Plan, Next step, Tool call.
- **Planning rules** — numbered plan of 3–7 steps; step 1 is always reading the task; last step is always verification.
- **Action rules** — prefer cheap probes, never repeat identical calls, don't dump binaries.
- **Turn budget discipline** — ≤30% of turns on exploration; when <20% remain, submit minimal.
- **Completion** — a content-only final message with no tool call ends the run.

### `skills/plan.md`

The decomposition protocol. Extract the grader contract first (what files, what shape). Decompose into 3–7 concrete steps with observable outcomes. Write the plan verbatim into every subsequent message until revised.

### `policies/stop-loops.md`

Never repeat a tool call with identical arguments. If the last observation didn't give new information, change the tool, the flags, or the scope — don't retry.

### `policies/submit-early.md`

When less than 20% of the turn budget remains, freeze the plan, collapse non-artifact-producing steps, write the minimal artifact with assumptions commented in, verify, submit. A partial artifact beats an articulate refusal.

### `config.yaml`

```
max_turns: 40
temperature: 0.2
max_tokens_per_call: 2048
best_of_n: 1
```

### Composition

`prompts.py` reads `prompts/system.md`, then every `skills/*.md` in sorted order, then every `policies/*.md` in sorted order, concatenates them with `\n\n---\n\n` separators, and exports `SYSTEM_PROMPT`.

This means **adding a skill or policy is a one-file change with no glue code**. That is the property the optimizer needs to search efficiently.

---

## 6. Measurement and attribution

Every scored trial produces a row in `runs/ledger.jsonl`:

```
{
  "timestamp":    "2026-04-20T10:43:12Z",
  "job_name":     "baseline_2026-04-20__12-34-11",
  "task_name":    "terminal-bench/fix-git",
  "trial_name":   "fix-git__abc123",
  "reward":       0.0,
  "turns":        20,
  "max_turns":    40,
  "prompt_hash":  "04b78e2f98880b07",
  "config":       { "max_turns": 40, "temperature": 0.2, ... },
  "failure_tag":  "graceful_giveup",
  "runtime_sec":  1051.1
}
```

Two fields matter most:

- **`prompt_hash`** — sha256 of the composed `SYSTEM_PROMPT` (first 16 hex chars). This is the **identity of a configuration**. Every score is attributable to a prompt_hash; every prompt_hash is reproducible from the editable surface.
- **`failure_tag`** — one of `success`, `partial`, `turn_exhaustion`, `graceful_giveup`, `tool_error_cascade`, `unknown_zero`. Computed heuristically from the trajectory in `scripts/record_baseline.py`. This gives the optimizer and the human reviewer a **qualitative** handle on zero scores, not just the number.

Without these two fields the ledger is a list of numbers with no way to say "this change caused that outcome."

### Subsets

**Status: proposed; pending empirical validation.**

`eval/subsets.py` exposes `EASY_SUBSET`:

```python
EASY_SUBSET = [
    "fix-git",                  # 7-line reference solution (reflog + merge)
    "openssl-selfsigned-cert",  # ~98-line procedural recipe
    "git-leak-recovery",        # well-scoped secret scrub
]
```

The picks were chosen because their reference solutions are short and procedural, which makes them *plausibly* within Gemma's ceiling. Whether this subset actually produces useful score variation for Gemma — rather than three zeros — is the hypothesis the next baseline run tests.

The working rule (don't calibrate on tasks the model can't solve) stands on its own merits; the specific three tasks remain provisional until at least one of them scores non-zero. If all three still zero out, the first response is to inspect trajectories before changing the subset.

---

## 7. The AutoResearch loop

Inner loop (one iteration):

1. Read the agent's current operating state (see §8 below)
2. Pick the single change with the strongest prior — from MEMORY.md or a named hypothesis
3. Apply it to the editable surface (`prompts/`, `skills/`, `policies/`, `config.yaml`)
4. Confirm the new `prompt_hash` differs from baseline (otherwise the change had no effect on the composed prompt)
5. `bash scripts/baseline.sh` — EASY_SUBSET × 3 attempts
6. `python scripts/record_baseline.py jobs/<job_name>` — append ledger rows
7. Inspect mean reward, per-task reward, failure-tag distribution
8. Append a dated entry to `memory/learnings.md` (hypothesis / change / result / verdict)
9. Decide:
   - Confirmed, held across this iteration → keep; update CONTEXT.md
   - Confirmed across two iterations → promote to MEMORY.md
   - Underperformed → add to DONT_DO.md and revert

Outer loop (when inner plateaus):

- Widen the task subset one tier
- Add a new artifact type only after MEMORY.md shows the existing surface has been exhausted
- Handoff note summarizing state, proposal, open questions

The optimizer in `optimizer/` is not yet wired to drive the inner loop; the same loop is currently driven by hand, which is the right place to be while prompts/policies are still being shaped.

---

## 8. The openclaw agent layer

**Status: built; only partially exercised.** The repo is the execution surface. The openclaw agent folder is the **evidence bank and operating contract** — what survives across iterations, what gets remembered, and what gets actively avoided.

Location: `~/.openclaw/workspace/agents/gemma-agent/`

```
gemma-agent/
├── README.md           # mission + handoff rules
├── SOUL.md             # identity + non-negotiables
├── OPERATING_RULES.md  # hard rules (editable-surface scope, attribution, honesty)
├── PROCESS.md          # the inner/outer loops codified
├── CONTEXT.md          # current state: active item, prompt_hash, next action
├── WIP.md              # what's being worked on now
├── MEMORY.md           # durable validated facts (curated)
├── DONT_DO.md          # anti-patterns (curated)
├── CHANGELOG.md        # history of agent-folder edits
└── memory/
    └── learnings.md    # append-only raw insights per iteration
```

### The self-improvement loop

This is the part that matters. Three files, three roles:

- **`memory/learnings.md`** — append-only, dated, noisy by design. One entry per iteration with: prompt_hash, hypothesis, change, result (mean reward + per-task + failure tags), verdict.
- **`MEMORY.md`** — curated durables. A learning is promoted here only after it has held across **two or more** iterations. Examples: "temperature 0.2 beats 0.5 on EASY_SUBSET," or "adding a worked-trajectory few-shot to `prompts/examples/` added 0.15 mean reward across 6 trials."
- **`DONT_DO.md`** — the anti-pattern file. Consulted before any new iteration. Example: "don't tune on make-mips-interpreter — beyond model ceiling, score changes are noise."

The discipline is simple: **every iteration appends to `learnings.md`**; nothing promotes to MEMORY.md on one data point; every iteration starts by reading DONT_DO.md.

Without this loop, AutoResearch re-discovers the same failures repeatedly and the operator cannot see why the optimizer made the choices it did. With it, the project compounds.

### Related openclaw artifacts

- **`~/.openclaw/workspace/agents/REGISTRY.md`** — lists `gemma-agent` as an active agent with its model and purpose
- **`~/.openclaw/workspace/handoffs/gemma-harness-*.md`** — formal handoff notes at turning points (today's note: `gemma-harness-artifact-surface-2026-04-20.md`)
- **`gemma-harness/docs/PROGRESS_<date>.md`** — daily progress notes (the pattern started on 2026-04-20)

---

## 9. Current state (2026-04-20)

**Blunt summary:** the harness is infrastructure-ready but **not yet benchmark-competitive**. The first meaningful post-fix validation run completed successfully end-to-end — and still scored 0.0. The project's current bottleneck is agent performance, not infrastructure.

### Status table

| Item | Status |
|---|---|
| Harbor install + CLI | Validated |
| Terminal-Bench 2 dataset path (`terminal-bench/terminal-bench-2`) | Validated |
| Docker-backed Harbor task execution | Validated |
| Oracle agent on terminal-bench-2 (score = 1.000) | Validated |
| `gemma-harness` as Harbor BaseAgent | Validated |
| Tool execution inside task container | Validated |
| Multi-turn agent loop stability (after `cwd` + `reasoning_content` fixes) | Validated |
| Pre-change baseline score (`prompt_hash 04b78e2f`, `make-mips-interpreter`) | Validated = 0.00, tag `graceful_giveup` |
| Editable artifact surface (prompts / skills / policies / compose) | Built, **not yet validated** |
| `EASY_SUBSET` usefulness as calibration set | Proposed, **pending validation** |
| Non-zero score on any Terminal-Bench 2 task | **Not yet achieved** |
| Ledger recorder (`prompt_hash`, `failure_tag`) | Built; exercised on the MIPS job |
| OpenClaw `gemma-agent` folder + self-improvement loop | Built; structure in place, loop not yet exercised |
| AutoResearch optimizer wired to drive iterations | **Not yet wired** |

### The one measurement we have

- Pre-artifact-surface baseline: `prompt_hash 04b78e2f98880b07` (the old one-liner system prompt) → 0.00 on `make-mips-interpreter`, tagged `graceful_giveup`, 20 of 40 turns used
- Any score under the new composed `SYSTEM_PROMPT`: not yet measured. The next baseline run is the first time the new surface is tested against reality.

### Recently built, awaiting validation

- `prompts/system.md`, `skills/plan.md`, `policies/stop-loops.md`, `policies/submit-early.md`
- `prompts.py` rewritten to compose from the markdown
- `eval/subsets.py` populated with `EASY_SUBSET`
- `scripts/baseline.sh` rewritten + `scripts/record_baseline.py` added (recorder dry-run verified)
- `~/.openclaw/workspace/agents/gemma-agent/` initialized with the full openclaw template
- Registry entry + handoff note + progress note

---

## 10. Next actions

Short list, ordered:

1. **Run the baseline** under the new `prompt_hash`:
   ```bash
   cd ~/.openclaw/workspace/gemma-harness
   bash scripts/baseline.sh
   ```
   Expected runtime: 10–30 min warm, longer cold. Output: ~9 rows in `runs/ledger.jsonl`.

2. **Append the result** to `~/.openclaw/workspace/agents/gemma-agent/memory/learnings.md`:
   hypothesis / change / per-task result / verdict.

3. **If any EASY_SUBSET task scored > 0**: the "get off zero" target is hit. Write the next progress note; promote the relevant artifacts as validated (to MEMORY.md after a second confirmatory run).

4. **If all still zero**: inspect the trajectories — the most likely next diagnostic is that Gemma's emitted `content` doesn't match the output-contract shape the prompt asks for. Candidate next change: a worked-example trajectory under `prompts/examples/` showing a full Observation/Plan/Next step/Tool call turn.

5. **Only after** the inner loop is producing consistent non-zero scores on EASY_SUBSET: widen the subset, wire the optimizer in `optimizer/` to drive the inner loop automatically.

---

## 11. Open decisions

- **Preserve `reasoning_content` in the trace** for diagnostics. The harness currently strips it from history (necessary — server rejection) but doesn't save it anywhere. If Gemma *is* reasoning, we can't see it. Proposed: save it to a side field in the trace record; diagnostic-only; no behavior change. Requires editing `harness/harness.py`, which is officially locked.

- **Add a few-shot worked trajectory** under `prompts/examples/`. Not added yet because no evidence it's needed — but if the baseline run shows Gemma still emits empty `content` despite the new output contract, this is the likely next lever.

- **Expose `config.yaml` `max_turns` and `temperature` to the optimizer search space**, or keep them operator-controlled. Smaller editable surface → faster convergence; larger surface → higher ceiling. Recommendation: operator-controlled until the prompt/skill/policy surface plateaus.

---

## 12. Glossary

- **Harbor** — the benchmark orchestrator that runs Terminal-Bench 2 against an agent. Installed in `~/miniconda3/bin/harbor`.
- **Terminal-Bench 2** — a benchmark of 89 terminal-centric tasks, each scored by a per-task verifier.
- **Oracle agent** — a reference agent that has the expected solution. Used to prove the benchmark stack works.
- **AutoResearch** — the outer loop that mutates the editable surface, scores, and promotes. Karpathy-style.
- **Prompt_hash** — sha256[:16] of the composed `SYSTEM_PROMPT`. The identity of a configuration.
- **Failure tag** — qualitative classification of a non-success trial.
- **EASY_SUBSET** — the 3 tasks used for "get off zero" calibration.
