# Tools workshop — living inventory (2026-04-23)

**Status:** working document. Use this to workshop which additional tools are worth adding to the harness. Not a decision log; decisions go into dated DESIGN docs once a tool is selected.

**Audience:** whoever is iterating on the agent scaffold next. Assumes familiarity with `docs/DESIGN_2026-04-23_tool_surface_expansion.md` (the `write_file` / `python` / `r` addition) and the full-benchmark ledger under `runs/ledger.jsonl`.

## How this doc is meant to be used

1. Each candidate has a **signature**, **what it replaces**, **evidence of need**, and **trade-offs**.
2. Tiers reflect priority based on observed benchmark behaviour, not gut feeling. Tier 1 has direct ledger evidence; Tier 4 is explicitly rejected with a reason so we don't re-visit.
3. When a tool graduates from "candidate" to "proposed," promote it to its own DESIGN_YYYY-MM-DD_tool_*.md doc.
4. When a tool ships, remove from this doc and add a one-line entry to `MEMORY.md` under "Current tool surface."

## Current tool surface (shipped)

| Tool | Use |
|---|---|
| `bash(cmd)` | Generic shell execution |
| `python(code)` | Python 3 via stdin |
| `r(code)` | Rscript via stdin |
| `write_file(path, content)` | Unconditional write, base64 round-trip |
| `file_view(path)` | Read entire file |
| `file_edit(path, old_text, new_text)` | Unique-match replace |
| `grep(pattern, path)` | Recursive regex search |

## Evidence base

From the v3 full benchmark (job `full_benchmark_2026-04-23__13-44-54`), partial data at ~4h mark:

- **Total bash calls across scored trials: 334**
- **23 bash commands over 1500 characters** — still heredoc-style despite write_file availability
- **45 raw `python3`/`python` invocations via bash vs 2 `python` tool calls** — the model is ignoring the dedicated Python tool in most cases (prompt-guidance gap, not tool-capability gap)
- **22 `cat` calls + 7 `head` calls = 29 file-inspection reads** — file_view reads whole files, which is expensive for large source trees
- **22 `apt-get` operations + 10 `DEBIAN_FRONTEND=noninteractive` prefixes** — compile/install tasks have a consistent install pattern
- **17 `ls` calls** — directory listing
- **Only 3 `curl`/`wget` calls** — network download is not a common blocker

This data drives the tiering below. Numbers update as the v3 run completes.

---

## Tier 1 — Ship next (direct ledger evidence)

### Prompt hardening for python/r usage

**Not a tool.** A prompt change. Listed first because it's the highest-leverage cheap win.

**Current state:** `prompts/system.md` says "For short Python snippets (<30 lines), use `python(code)` directly." Gentle suggestion.

**Evidence:** 45 bash `python3` invocations vs 2 `python` tool calls in v3. The model's default pattern is sticky.

**Proposed:** upgrade to a hard rule:

> If your bash command starts with `python3`, `python`, `Rscript`, or `R`, use the `python(code)` or `r(code)` tool instead. This is mandatory, not optional. Bash is for shell operations (running binaries, file ops, package install), not for invoking language runtimes.

**Cost:** 1 paragraph edit in `prompts/system.md`. New `prompt_hash`.

**Trade-offs:** (+) lifts ~40 bash-python calls onto the direct path, shrinks per-turn argument size, avoids shell-escape issues. (−) adds specificity the model might over-index on; if a task legitimately needs bash-scoped Python (e.g. with env vars in the shell context), the rule might backfire. Acceptable trade.

**Open questions:** do we need a similar rule for Rscript? Yes — cheap to include.

---

### `read_file_range(path, start_line, end_line)`

**Replaces / complements:** `file_view` (when file is large) and bash `head`/`tail`/`sed -n 'X,Yp'`.

**Evidence of need:** 22 bash `cat` + 7 `head` = 29 file-inspection calls via bash. `file_view` returns the whole file regardless of size. On tasks with large source files (multi-kLoC), this wastes context budget.

**Signature:**
```
read_file_range(path: str, start: int = 1, end: int | None = None)
  → { "content": str, "total_lines": int, "range": [start, end] }
```

**Implementation:** ~15 lines. Use `sed -n 'START,ENDp' path` via `environment.exec`. If `end` is omitted, default to `start+200`.

**Trade-offs:** (+) bounded context cost on large files; (+) structured return makes it easy for the model to ask for "next 200 lines" on follow-up. (−) one more tool for the model to choose among; `file_view` is still the right choice for small files. Tool description should be explicit: "Use this instead of `file_view` when the file exceeds ~500 lines."

**Open questions:** sub-file addressing — do we also want offsets by byte or function name? No, not yet. Line-based is enough.

---

### `apt_install(packages, yes=True)`

**Replaces / complements:** bash `apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y <packages>`.

**Evidence of need:** 22 apt operations + 10 DEBIAN_FRONTEND prefixes observed. The pattern is uniformly `apt-get update && apt-get install -y ...` with various `sudo` / env-var juggling. Dedicated tool standardizes it.

**Signature:**
```
apt_install(packages: list[str], update: bool = True)
  → { "ok": bool, "installed": [...], "stderr": str }
```

**Implementation:** ~20 lines. Server-side always runs `DEBIAN_FRONTEND=noninteractive apt-get ...`. Optionally runs `apt-get update` first (default true; first call per trial).

**Trade-offs:** (+) removes 30+ characters of boilerplate per install; (+) faster, more reliable (no forgetting `-y` or `DEBIAN_FRONTEND`); (+) standardizes error handling. (−) model has to learn to use it instead of bash. Prompt guidance should cover this.

**Open questions:** add a `pip_install(packages)` sibling? Probably yes — low cost, similar pattern. Also common. If both, maybe unify under `install(packages, manager="apt"|"pip"|"auto")`. Defer; workshop.

---

### `apply_patch(path, unified_diff)`

**Replaces / complements:** `file_edit` when multi-hunk or multi-file; long bash `sed`/`patch` heredocs.

**Evidence of need:** 23 bash commands over 1500 characters. Inspection shows many of these are `sed -i` scripts or `cat > file << EOF\n<diff>\nEOF && patch -p0 < file` patterns. `file_edit` requires unique `old_text`, which fails when similar text appears in multiple places in the file.

**Signature:**
```
apply_patch(path: str, diff: str)
  → { "ok": bool, "hunks_applied": int, "stderr": str }
```

Accepts a unified diff. Uses `patch -p0` server-side.

**Implementation:** ~30 lines. Base64-encode the diff, write to a temp file, run `patch -p0 -i tempfile target`.

**Trade-offs:** (+) handles multi-hunk edits that `file_edit` can't; (+) correct pattern for LLMs, which are good at diff generation; (+) standard format — easier to reason about failures. (−) more complex tool description; may confuse on simple single-line edits where `file_edit` is cleaner. (−) diffs can fail to apply cleanly; error handling matters.

**Open questions:** accept context-less diffs (just the changed lines) or require standard unified format? Require standard (3 lines of context). Easier to verify.

---

## Tier 2 — Strong rationale, workshop

### `done(summary: str)`

**Replaces / complements:** current "emit a content-only message with no tool_calls" pattern for trial completion.

**Evidence of need:** 3 `server_bad_request` in 2026-04-22 run involved the model hitting `finish_reason="stop"` with malformed content, tripping the prefill-on-thinking check. An explicit submit tool would make completion unambiguous.

**Signature:**
```
done(summary: str)
  → { "ok": true, "terminated_by": "done" }
```

Behaviour: the harness sees this tool call, records the summary as the trial's final message, and terminates immediately (no next chat call).

**Implementation:** ~15 lines in `harness/harness.py`. Treat it specially: execute, then return with `status="done_explicit"`.

**Trade-offs:** (+) cleaner contract; (+) removes one class of prefill-related 400s entirely; (+) machine-readable completion state for the ledger. (−) changes the model's mental model of completion — might forget to call it and hit turn_exhaustion instead.

**Open questions:** force it (require `done()` to pass), or optional? Optional initially — existing "no tool_calls + stop" still works.

---

### `list_files(path: str = ".", glob: str = "*", recursive: bool = False)`

**Replaces / complements:** bash `ls`, `find`.

**Evidence of need:** 17 `ls` calls, plus some `find` use. Both are fine via bash but have output-parsing overhead on the model side.

**Signature:**
```
list_files(path=".", glob="*", recursive=False)
  → { "files": [...], "dirs": [...], "truncated": bool }
```

**Implementation:** ~20 lines. Uses `find path -maxdepth 1 -name glob` or `find path -name glob`.

**Trade-offs:** (+) structured return easier than parsing `ls` output; (+) bounded output (cap at 200 entries, mark truncated). (−) marginal win — bash `ls -la` is fine and the model is good at reading it.

**Open questions:** bigger win if we include `size`, `mtime`, `type` in the structured output. Probably yes.

---

### `pip_install(packages)`

**Replaces / complements:** bash `pip install <packages>`.

**Evidence of need:** moderate. Many ML tasks (`caffe-cifar-10`, `pytorch-*`, `train-fasttext`) need pip installs. But the pattern `pip install X` is already very short in bash; the win is smaller than `apt_install`.

**Signature:**
```
pip_install(packages: list[str], user: bool = False)
  → { "ok": bool, "installed": [...], "stderr": str }
```

**Implementation:** ~15 lines. Wraps `pip install` or `pip install --user`.

**Trade-offs:** (+) some standardization; (+) paired with `apt_install` for consistent install semantics. (−) very small win over bash; arguably not worth the additional tool in the schema.

**Recommendation:** unify with `apt_install` under a single `install(manager, packages)` tool, OR ship only if `apt_install` proves high-value first.

---

### `git(subcommand: str, args: list[str] = [])`

**Replaces / complements:** bash `git <whatever>`.

**Evidence of need:** many tasks are git-centric (`fix-git`, `git-leak-recovery`, `sanitize-git-repo`, `git-multibranch`, `configure-git-webserver`). Currently model uses `bash(cmd="git log --oneline")` etc.

**Signature:**
```
git(subcommand: str, args: list[str] = [])
  → { "stdout": str, "stderr": str, "returncode": int }
```

**Implementation:** ~10 lines. Trivial wrapper over `bash`.

**Trade-offs:** (+) slight ergonomic improvement; (+) arguably clearer intent in trace. (−) near-zero functional benefit — bash already runs git cleanly; adding a tool just to rename the caller is overhead.

**Recommendation:** **skip.** Bash is the right shape for git. Revisit only if we discover structural issues with bash-git.

---

## Tier 3 — Niche / specialized

### `jq(input: str, expr: str)`

For JSON-query-heavy tasks. Limited scope.

**Recommendation:** defer until we see >5 tasks benefit.

### `sqlite_query(db_path: str, sql: str)`

For SQLite tasks (`sqlite-db-truncate`, `sqlite-with-gcov`, `db-wal-recovery`). Currently 3-4 candidate tasks.

**Recommendation:** defer. Bash `sqlite3 db "SQL"` works fine; structured output is not a blocker.

### `http_get(url: str)` / `download(url: str, path: str)`

Only 3 curl/wget operations observed across scored trials. Not a pattern.

**Recommendation:** skip unless data changes.

### `run_tests(spec: str = "pytest")`

Formal test runner. Most grader-facing tasks have their own test harness; the agent just runs it once.

**Recommendation:** skip. Bash call to `pytest` or the task's specific verifier is fine.

### `node(code: str)` / `js(code: str)`

For tasks like `filter-js-from-html`, `break-filter-js-from-html`. Currently two tasks.

**Recommendation:** borderline. If v3 shows these tasks hitting heredoc issues with large JS programs, add. Otherwise defer.

### `elf_info(path: str)` / `disassemble(path, start, end)`

For `extract-elf`, `make-mips-interpreter`, `make-doom-for-mips`. Currently done via bash `readelf`/`nm`/`objdump`.

**Recommendation:** skip. Model already uses these correctly via bash; no evidence of a bottleneck.

---

## Tier 4 — Rejected (do not re-raise without new evidence)

### `terminal_session(cmd)` — persistent interactive shell

**Rejected because:** every tool call is a new `environment.exec`. Persistent state is incompatible with Harbor's container lifecycle. Tasks that need stateful sessions can use `write_file` + `bash` to compose scripts.

### `sed(path, expr)` / `awk(path, expr)` — dedicated stream editors

**Rejected because:** bash handles these cleanly; dedicated tools are cognitive-load-heavy for marginal benefit. `apply_patch` covers the multi-line-edit case.

### `submit_to_verifier()` — bypass the default verification

**Rejected because:** the verifier is Harbor's responsibility, not the agent's. Offering a bypass invites reward hacking. The only model-visible completion signal is "stop" or `done()`.

### `sudo(cmd)` — elevated bash

**Rejected because:** `environment.exec` already runs as whatever user the task container uses. Sudo concerns are out of scope.

### `ssh(host, cmd)` — remote execution

**Rejected because:** relevant tasks (`qemu-alpine-ssh`, `qemu-startup`) are single-machine via qemu. No remote hosts in scope.

---

## Cross-cutting: prompt-level improvements that aren't tools

These are listed here because they affect tool usage without requiring new tools.

### T1. Hard tool-selection rule

Already covered above. Force python/r tool usage by rule rather than suggestion.

### T2. Self-review turn before completion

Force the model to call `file_view` or `ls` on the expected artifact path before emitting `done()` / stop. Catches "forgot to create the file" failures.

**Open question:** worth it or prompt bloat?

### T3. Explicit error-recovery rule

On tool error (returncode != 0 or error field present), the next turn *must* start with a one-sentence diagnosis before the next action. Currently the model sometimes just retries.

**Open question:** prompt-engineer it, or add a harness-side guard that injects the rule as a tool_result for failed calls?

### T4. Initial task-shape-detection

First turn's plan should include "what kind of artifact does the grader check?" (file content, command output, state change). Different answers lead to different tool shapes.

---

## Open workshop questions

- **Unified `install(manager, packages)` vs separate `apt_install` + `pip_install`?** Separate is clearer; unified is more extensible. Lean separate for now.
- **Should `write_file` gain an `append` mode?** Evidence would be seeing cases where the model writes a file, needs to add a line, and has to re-write the whole thing. Not observed yet. Defer.
- **Should the harness enforce tool-call argument size limits?** Currently no cap on a tool argument string. A 10KB bash command is reasonable; a 100KB one is a sign the model is dumping heredocs and should have used `write_file`. A soft warning via tool_result would be a behavioural nudge.
- **Do we want per-tool timeouts that show up in the ledger?** Currently `model_timeout_sec` is a per-chat-call cap. A `tool_timeout` per `bash`/`python`/etc. call would let us distinguish "agent burned 60s thinking" from "agent burned 60s running slow binary." Non-trivial instrumentation work.
- **Do we add `fast_eval_verify(task)` for AutoResearch's L1 reward?** Cross-cutting with the fast-eval-proxy design doc. Belongs in that workstream, not here.

---

## Concrete shipping slate (if we shipped today)

Ordered by leverage-to-effort ratio. Each becomes its own small commit with prompt_hash change.

1. Prompt hardening (§Tier 1 first entry) — free
2. `read_file_range` — ~15 lines
3. `apt_install` — ~20 lines
4. `apply_patch` — ~30 lines
5. `done(summary)` — ~15 lines of harness change

Estimated total: 80 lines of tools.py, 1 paragraph of prompts/system.md, ~20 lines of harness.py change for `done`. One `prompt_hash` transition covers all of it.

**Target metric for the next benchmark after these land:** write_file + python + r combined usage > 30 calls per full run; bash `python3` invocations < 5. Proof that the tool-selection rule is working.

---

## References

- `docs/DESIGN_2026-04-23_tool_surface_expansion.md` — the write_file/python/r decision
- `docs/Design 2026 04 22 fast eval proxy · MD` — cross-cutting eval design that touches some of the same surface
- `runs/ledger.jsonl` — all trial outcomes (source of the evidence counts above)
- `harness/tools.py` — current tool implementations
- `prompts/system.md` — current system prompt

---

## Appendix A — Lessons from other agent frameworks

Everything below is prior art. Use it as a menu of ideas, not a must-adopt list. For each framework, I've surfaced the **genuinely distinctive design choices** rather than repeating the common "bash + write + grep" baseline.

### Claude Code (Anthropic's official CLI — the harness you're talking to right now)

Tools exposed: `Read`, `Write`, `Edit`, `NotebookEdit`, `Glob`, `Grep`, `Bash`, `Task*`, `Skill`, `Agent`, `WebFetch`, `WebSearch`, `AskUserQuestion`, `ScheduleWakeup`, `Monitor`, `ToolSearch`.

**Distinctive design choices worth borrowing:**

- **Read-before-Edit/Write discipline.** The harness tracks which files you've read in the current session; `Edit`/`Write` on an unread existing file errors out. Catches "assumed X was in the file" bugs. ~5 lines of state-tracking in the harness.
- **Separated Glob (path discovery) vs Grep (content search).** Two small tools with clear roles outperform one big `search` tool. Glob returns paths sorted by mtime — a small but useful affordance.
- **Three-mode Grep.** `content` / `files_with_matches` / `count`. Same tool, three answer shapes. Model picks the cheapest mode for the question.
- **Structured Task tracking** (`TaskCreate`, `TaskUpdate`, `TaskList`, etc.). Forces multi-step plans to be visible and machine-readable. Status state machine (`pending → in_progress → completed`) is enforced.
- **`Agent` as a tool.** Sub-agent delegation is a first-class primitive; the main loop can spawn a bounded sub-loop for heavy sub-tasks. Comes with optional background execution.
- **`ToolSearch` / deferred schema loading.** Not every tool's schema is in context at all times — only tool *names* are. Schemas get loaded on-demand via `ToolSearch`. Context-efficiency pattern for harnesses with >15 tools.
- **`Skill` as invocable playbook.** Named, versioned playbooks (update-config, fewer-permission-prompts, etc.) that encapsulate multi-step procedures. Roughly analogous to our `skills/*.md` but tool-invokable.
- **`ScheduleWakeup`** for self-pacing in long runs (the tool this session uses to check on the benchmark between wakes).

**Design rules not borrowable:** WebFetch/WebSearch (out of scope, no network for Terminal-Bench), AskUserQuestion (no human in benchmark loop).

### OpenClaw (Ben's own system, for context)

OpenClaw isn't a tool framework — it's a **structural convention** for agent identity, memory, and handoff. The "tools" are *artifacts* on the filesystem:

- **Identity files** per agent: `SOUL.md`, `OPERATING_RULES.md`, `PROCESS.md`, `CONTEXT.md`, `MEMORY.md`, `DONT_DO.md`.
- **Skills** as named, version-controlled markdown directories under `~/.openclaw/workspace/skills/`, reusable across agents.
- **Handoff protocol**: durable handoff notes in `~/.openclaw/workspace/handoffs/` mark transfer of work between agents or phases.
- **Self-improvement loop**: append-only `memory/learnings.md` per iteration; promote validated insights to `MEMORY.md`; anti-patterns to `DONT_DO.md`. Mirrored in our `gemma-agent/` folder today.
- **Registry + governance** (`REGISTRY.md`, `GOVERNANCE.md`, `ESCALATION_LOG.md`) — tracks which agents exist and who owns them.

**Distinctive vs LLM-framework thinking:** OpenClaw treats *durable state between runs* as the first-class primitive. Most agent frameworks focus on within-run state. Worth borrowing when an agent is meant to persist across sessions.

### LangChain / LangGraph

LangChain is the biggest "tool pantry" — the canonical list is large. Built-in categories:

- **Code execution:** `PythonREPLTool`, `PythonAstREPLTool` (persistent REPL), `ShellTool`
- **Search:** `DuckDuckGoSearchRun`, `SerpAPIWrapper`, `TavilySearchResults`, `WikipediaQueryRun`, `ArxivQueryRun`, `PubmedQueryRun`
- **Math:** `LLMMathChain`, `WolframAlphaQueryRun`
- **File ops:** `WriteFileTool`, `ReadFileTool`, `ListDirectoryTool`, `CopyFileTool`, `DeleteFileTool`, `MoveFileTool` (all under `FileManagementToolkit`)
- **HTTP:** `RequestsGetTool`, `RequestsPostTool`, etc.
- **Structured data:** `JsonToolkit`, `SQLDatabaseToolkit` (query + schema discovery + list-tables), `OpenAPIToolkit`
- **RAG:** `VectorStoreQATool`, retriever-as-tool abstractions
- **Agent orchestration:** `AgentExecutor`, multi-tool chains

**Distinctive design choices worth considering:**

- **`SQLDatabaseToolkit` as a *toolkit*** — a bundle of tools (list_tables, get_schema, query) that work together. Useful mental model when we add `sqlite_query` later.
- **LangGraph state machines.** Agents as explicit state graphs with checkpoints, human-in-the-loop interrupts, and resumable runs. Overkill for single-trial benchmarking, but relevant if we ever want pause/resume on a long trial.
- **Persistent Python REPL.** `PythonAstREPLTool` keeps variables across calls — the model can `x = compute()` then on a later turn `print(x.shape)` without recomputing. We don't have this (every `python(code)` call is a fresh interpreter).

**Not borrowable directly:** the majority of LangChain's tool pantry (Wikipedia, Wolfram, DuckDuckGo) is irrelevant to local-container benchmarks.

### SWE-agent (Princeton — the closest prior art to what we're doing)

Coined **ACI = Agent-Computer Interface**: the observation that LLM agents perform dramatically better when given tools designed for LLMs rather than raw shell. Their core insight applies directly to us.

**Their custom tool set:**

- **Viewport file viewer.** `open(file)` shows a 100-line window with a scroll position. Subsequent `scroll_up` / `scroll_down` moves the window. Full file contents are never dumped; context cost stays bounded regardless of file size.
- **`goto(line)`** — jump the viewport to a line number.
- **`search_file(pattern)`** — search within the currently-open file.
- **`search_dir(pattern, [dir])`** — search across directory.
- **`find_file(name)`** — find a file by name.
- **`edit(start_line, end_line, replacement)`** — line-range-based replacement. No "unique old_text" requirement; explicit coordinates.
- **`create(filename)`** — create empty file, open it in viewport.
- **`submit()`** — explicit submission of the current state as the answer.

**Takeaways for our harness:**

- Our Tier-1 `read_file_range` is basically SWE-agent's viewport. Strong validation — this pattern is the single most-cited ACI win.
- Our Tier-2 `done(summary)` mirrors SWE-agent's `submit`.
- Their **line-based edit** is more robust than our uniqueness-based `file_edit`. `apply_patch(diff)` (Tier 1) captures the same idea via unified diff; alternative: `edit_lines(path, start, end, new_text)` — simpler, maybe worth a variant.

### OpenHands (All-Hands-AI, formerly OpenDevin)

Production-quality general-purpose agent scaffold. Strong emphasis on **persistent sessions**.

**Their distinctive tools:**

- **Persistent bash session.** `bash` isn't stateless — it keeps a shell alive across calls. `cd /app; export X=1` on turn 3 is still in effect on turn 7. Solves problems like "why did the model just run `cd` 53 times in v3?"
- **Persistent IPython session.** Same idea for Python. Variables persist; imports persist.
- **Browser automation** via Playwright: `browse(url)`, `click(selector)`, `fill(selector, text)`, `scroll`, `screenshot`.
- **Jupyter-notebook-style execution** with rich outputs (plots, DataFrames).
- **`edit`** with line ranges (similar to SWE-agent).

**Distinctive considerations:**

- Persistent sessions are a **double-edged sword**. Pro: massively fewer redundant commands (no `cd`-per-turn). Con: state leaks between tool calls, harder to reason about observability ("did the last `echo $X` just print stale state?"). Worth an experiment but needs care.
- Browser tools are out of scope for Terminal-Bench but would matter for web-task benchmarks.

### Aider (pair-programming CLI)

Focused specifically on code editing in an existing git repo. Not directly an agent benchmark tool but the design is crisp.

**Distinctive design choices:**

- **Repository map.** On startup Aider builds a tree-sitter AST summary of the repo — list of files + key symbols per file. Provided to the model as initial context. Reduces "grep around blindly" turns on large repos.
- **Edit formats.** Configurable: whole-file, udiff-style, or "SEARCH/REPLACE block" (exact match). The model picks the cleanest format per change. Their ablations show the choice matters more than you'd think.
- **Git-backed commits.** Each successful edit is auto-committed with a generated message. Trivial rollback if a change is wrong.
- **Undo tool.** The model can `undo` a previous commit if it went wrong.

**Takeaways:**

- A **repo map on turn 1** is probably worth it for tasks like `sanitize-git-repo`, `git-leak-recovery` — would save 10+ turns of `ls -R` and `find`. Cost: one server-side pass of `find` or `tree-sitter-based` summary per task setup. Worth workshopping as a `task_setup_info` tool or a hidden pre-turn context injection.
- The **multi-format edit** idea generalizes our `file_edit` + `apply_patch` split. Aider's third mode (SEARCH/REPLACE) is functionally identical to our `file_edit`; our `write_file` + `apply_patch` cover the other two.

### AutoGen (Microsoft)

Multi-agent conversation framework.

**Distinctive design choices:**

- **Agent-to-agent messaging** as the primitive. "UserProxyAgent", "AssistantAgent", "GroupChatManager" orchestrates.
- **Code executor** abstraction (local Docker or remote) used by all agents — clean separation of "what to execute" vs "where to execute."
- **Conversation termination rules** (like "end when someone says TERMINATE").

**Takeaways:**

- Multi-agent patterns are **overkill for single-trial benchmarking**, but if we ever wanted to explore "planner agent + executor agent" structures, AutoGen's decomposition is clean.
- Their code-executor abstraction is useful framing for our own `environment.exec` boundary.

### ReAct / plain tool-use (the baseline)

Thought → Action → Observation. No special tool discipline beyond function schemas.

**Takeaway:** This is what most basic LLM-agent frameworks reduce to. Everything above is a layer on top of this baseline. We're operating at ReAct + function-calling with some discipline (protocol drift defense, structured ledger, tiered eval). That's already a fairly sophisticated scaffold.

---

## Appendix B — Prioritized takeaways from the cross-framework survey

Ranked by likely impact on our benchmark Pass@1, given the evidence we have.

| Idea | Source | Tier | Comment |
|---|---|---|---|
| Viewport file reader (`read_file_range`) | SWE-agent | 1 | Already in our shipping slate. Strong validation. |
| Apply-patch / line-range edit | SWE-agent, Aider | 1 | Already in our shipping slate. |
| Structured `done(summary)` | SWE-agent, Claude Code | 2 | Already in our shipping slate. |
| Repository map on first turn | Aider | 2 | New idea — could save ~10 turns on git/repo tasks. Workshop. |
| Persistent bash session | OpenHands | 3 | Tempting (53 `cd` calls!) but state-leak risk. Workshop carefully. |
| Persistent Python REPL | LangChain, OpenHands | 3 | Same class as persistent bash. Lower-value for Terminal-Bench. |
| Read-before-Edit discipline | Claude Code | 3 | Small quality win; low implementation cost. |
| Three-mode `grep` | Claude Code | 3 | Small context-efficiency win. |
| `Agent` sub-delegation | Claude Code, AutoGen | 4 | Overkill for single-trial work. Revisit if task complexity grows. |
| Tool-search / deferred schemas | Claude Code | 4 | Only relevant at >15 tools. We have 7. |
| Multi-agent orchestration | AutoGen, LangGraph | 4 | Out of scope for a single-trial benchmark agent. |
| Browser automation | OpenHands | 4 | Out of scope (no web tasks in Terminal-Bench). |

## Appendix C — Concrete new candidates from the survey

Add to the tier list above:

### `repo_map(root=".")` — task-setup pass summarizing the working directory

**Source:** Aider.

**Signature:**
```
repo_map(root: str = ".", max_files: int = 200)
  → { "tree": str, "key_symbols": { "path": [symbols...], ... } }
```

Returns a compact tree-view of the working directory plus key symbols (function/class names) extracted from each Python/JS/Rust/C source file (via `ast.parse` for Python, `grep` for others — not full tree-sitter).

**Evidence of need:** on tasks that land the agent in a repo it doesn't know (git-leak-recovery, sanitize-git-repo, configure-git-webserver, many others), the first 3-5 turns are uniformly `ls`, `ls -R`, `find`, `grep -r`. A single `repo_map` call could replace that pre-amble.

**Trade-offs:** (+) reduces exploration turns, which is most valuable on 20-turn-capped runs. (−) may return too much context on huge repos; needs `max_files` truncation. (−) some tasks don't benefit (the "working dir" is a single binary, no source tree).

**Decision:** promote to Tier 2, workshop whether to invoke it automatically on turn 1 or leave as model-optional.

### `persistent_bash(cmd)` — stateful shell session

**Source:** OpenHands.

**Signature:**
```
persistent_bash(cmd: str, session: str = "default")
  → { "stdout", "stderr", "returncode", "session": "..." }
```

Keeps a shell process alive per trial. Subsequent calls share cwd, env vars, exported functions, background jobs.

**Evidence of need:** 53 `cd` calls in v3 suggest the model is wasting turns re-entering directories. Many task patterns are `cd /app && some_long_command && cd .. && other_command`.

**Trade-offs:** (+) ergonomic — matches real-world interactive shell experience. (+) ~20-30% turn reduction on tasks with many state-dependent commands. (−) state bugs are harder to debug — a failing command might depend on state set 5 turns ago. (−) requires managing pty lifetime + cleanup per trial.

**Decision:** promote to Tier 3, workshop — needs an A/B test run before shipping.

### `edit_lines(path, start, end, new_content)` — line-range replacement

**Source:** SWE-agent.

**Signature:**
```
edit_lines(path: str, start: int, end: int, new_content: str)
  → { "ok": bool, "lines_replaced": int }
```

Alternative to `file_edit` (unique-match) and `apply_patch` (unified diff). Explicit line coordinates. Easier for the model than generating a valid unified diff when it has read the file via `read_file_range` and knows exact line numbers.

**Trade-offs:** (+) easiest edit format for the model when line numbers are known; (+) pairs naturally with viewport reading. (−) a third edit tool to choose among. (−) line numbers can drift if prior edits changed file length.

**Decision:** **maybe skip.** `apply_patch` (Tier 1) covers this use case with a richer format. Only add if `apply_patch` proves too complex for the model to produce reliably.

### Three-mode `grep` / structured Grep

**Source:** Claude Code.

**Change:** our existing `grep(pattern, path)` gains an `output_mode` parameter: `"content"` (default, current behaviour), `"files_with_matches"`, `"count"`.

**Trade-offs:** (+) cheap; (+) context-efficiency win when the model just wants to know "does X exist in this dir?" (−) model has to remember the mode parameter.

**Decision:** promote to Tier 2, ship with Tier 1 batch. 5 extra lines of code.

---

## Appendix D — Architectural questions raised by the survey

These are **workshop items**, not decisions:

- **Should we make `environment.exec` the clean boundary it could be?** Today `bash`, `python`, `r`, `file_view`, `file_edit`, `write_file`, `grep`, `apt_install` (future) all call through `environment.exec`. The boundary is consistent. But we could formalize it more: the harness knows what Docker/task-container state looks like, and tools could run via structured invocation (like AutoGen's code-executor abstraction). Not urgent.

- **Do we want a task-setup "turn 0" tool like `repo_map`, or should this be a prompt-time context injection?** Two shapes with different trade-offs: as a tool, the model decides when to invoke (may skip it on simple tasks). As context injection, it's always there (cost on every task regardless of need). Workshop.

- **Is persistence (bash session, Python REPL) worth the observability hit?** Hard to tell without an A/B. Workshop — could be one of the first "real" AutoResearch iterations (same prompt, persistent vs stateless bash).

- **Do we lean toward "many narrow tools" (Aider, SWE-agent) or "few powerful tools" (ReAct, us currently)?** Narrow tools = easier for the model to pick right; many tools = schema bloat + choice paralysis. Current sweet spot feels like 8-12. Above 15 starts to need deferred loading (Claude Code's approach).
