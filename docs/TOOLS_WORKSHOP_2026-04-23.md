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
