# Design — Expand the agent tool surface to reduce parser-bug exposure (2026-04-23)

## Problem

The current harness exposes a single execution tool, `bash(cmd)`, plus `file_view`, `file_edit`, and `grep`. On tasks that require writing substantial program code (R scripts, Python modules, vim macros, polyglot files), Qwen3.6 in thinking mode reliably packs the entire program into a single `bash` call via a heredoc:

```
bash(cmd='python3 << "PYEOF"\n<500 lines of code with {…} blocks>\nPYEOF')
```

This triggers llama.cpp issue [#21384](https://github.com/ggml-org/llama.cpp/issues/21384): the server's tool-call streaming parser does not correctly handle `{` / `}` characters inside JSON string values. The request fails mid-stream with HTTP 500 (`Failed to parse tool call arguments as JSON`). Our harness catches this cleanly now (`status="server_tool_parse_error"`, per commit `064a3bb`), but the trial is lost.

Observed in the 2026-04-23 full benchmark run so far:
- **10+ HTTP 500s** in the server log, all of this form
- Each 500 kills a real attempt at a solvable task (adaptive-rejection-sampler, distribution-search, etc. — not inherent capability ceilings)
- Tasks like `polyglot-c-py`, `polyglot-rust-c`, `regex-chess`, `tune-mjcf` are structurally at risk because they require writing substantial multi-line program code

## Why the tool shape matters

The parser bug is triggered by the shape of the assistant's tool_call output, not the content of the task. Two root causes operating together:

1. **No natural alternative for "write code."** With only `bash` + `file_edit`, the model has no clean path to "put 200 lines of Python somewhere and run it." `file_edit` requires an existing file and a unique `old_text` to replace. The path of least resistance is a heredoc in `bash`.
2. **Heredoc-encoded strings are heavy.** Inside a heredoc the model emits every line of source verbatim, including all `{`/`}` characters. In a JSON tool_call argument these must be escaped, and the cumulative character count for a non-trivial program easily exceeds 6000 tokens of argument value.

These two combine into the worst-case input for the parser bug: long JSON string values with many unescaped-looking `{`/`}` sequences that confuse the state machine as tokens stream in.

## Goal

Reduce the per-tool-call argument size enough that the parser bug stops firing in practice, without changing the model or the prompt, and without waiting for the upstream llama.cpp fix. Preserve the behaviour that `bash` already handles well (short commands, one-liners, already-in-place scripts).

Non-goal: wire `llguidance` (PR #21697-derived grammar constraints). That's a larger, separate workstream. This design is the cheap short-term mitigation.

## Proposed additions

Three tools added to `harness/tools.py`. All are thin wrappers over `environment.exec`; no new infrastructure.

### `write_file(path, content)`

Writes `content` verbatim to `path` (absolute or cwd-relative), creating parent directories as needed. Replaces any existing file at `path`. Returns `{"ok": true, "path": path, "bytes": n}` on success; error dict otherwise.

Implementation: the existing `file_edit` already uses base64 round-trip to handle arbitrary content. `write_file` is the unconditional-overwrite variant:

```python
import base64
b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
r = await environment.exec(f"mkdir -p $(dirname {path}) && echo '{b64}' | base64 -d > {path}", cwd=cwd)
```

### `python(code, timeout=60)`

Executes `code` as a Python 3 program via stdin. No file round-trip, no heredoc, no PYEOF dance. Returns `{"stdout", "stderr", "returncode"}`.

Implementation:
```python
import base64
b64 = base64.b64encode(code.encode("utf-8")).decode("utf-8")
r = await environment.exec(f"echo '{b64}' | base64 -d | python3", cwd=cwd, timeout_sec=timeout)
```

### `r(code, timeout=60)` (optional)

Same pattern for Rscript. Only worth adding if `adaptive-rejection-sampler` / `rstan-to-pystan` / similar R-heavy tasks remain failure patterns after the above two land. Tracked as follow-on.

## Why this helps

**Shift the natural pattern from one-shot dumps to compose-then-run.** With `write_file` available the model shifts to:

1. `write_file(path='/app/solution.py', content='<program>')`
2. `bash(cmd='python3 /app/solution.py')`

Step 1 still has a long `content` string, but:
- The string is in a simpler JSON position (top-level argument, not nested inside a shell heredoc string)
- The model doesn't need to escape shell metacharacters, so the character count drops
- Subsequent turns (step 2) are short bash commands, zero parser risk

For short snippets the model uses `python(code)` directly, which encodes the code as a single JSON string argument (same as the current bash-heredoc pattern, but without the shell-escape noise — net smaller).

We expect this to reduce HTTP 500 rate significantly without eliminating it. The parser bug is still latent; we've just reduced the exposure surface.

## Prompt update

The system prompt (`prompts/system.md`) currently says:

> Run a bash command in the task working directory. Use for compiling, running tests, listing files, etc.

It should gain a paragraph noting the new tools and the preferred pattern:

> When writing substantial code (more than ~30 lines), use `write_file(path, content)` to land the file, then `bash(cmd="python3 path/to/file.py")` to run it. Avoid embedding large programs inside bash heredocs. For short Python or R snippets (<30 lines), use `python(code)` or `r(code)` directly.

This is a single `prompts/system.md` edit. `prompt_hash` changes, which is correct — this is a genuine agent-behaviour change and should be attributable in the ledger.

## Implementation plan

1. Add the three functions to `harness/tools.py`. Mirror the existing `bash` / `file_edit` implementation pattern (base64 round-trip, `environment.exec`).
2. Add their schemas to `TOOL_SCHEMAS`.
3. Register them in the `_TOOLS` dispatch dict.
4. Update `prompts/system.md` with the pattern guidance.
5. SMOKE on `fix-git` — confirm no regression.
6. Targeted re-run on the 4 tasks that hit `server_tool_parse_error` in the 2026-04-22 full benchmark (`adaptive-rejection-sampler`, `constraints-scheduling`, `distribution-search`, `extract-elf`) — confirm the parse error rate drops and scored outcomes improve.

Acceptance: `server_tool_parse_error` tag appears on ≤1 of those 4 tasks (vs 3-4 before), without introducing new failure modes.

## Ledger impact

Adding three tools adds three rows of schema to the system prompt, so `prompt_hash` changes from `d41e9732` to a new hash. All subsequent ledger rows carry the new hash and are directly comparable among themselves. Cross-hash comparisons (old vs new) are fair only if we hold other config constant (we will).

No new failure tags needed — existing ones cover the outcomes.

## Trade-offs

**Pro:**
- Cheap to implement (< 60 lines of code, one prompt edit)
- Attacks the biggest observed parser-bug trigger in real runs
- Backwards compatible — existing single-bash-tool trials still work

**Con:**
- More tools = more tokens in the system prompt = slightly higher per-turn cost
- Three new decisions for the model each turn = a tiny extra surface for confusion on simple tasks
- Does not *fix* the parser bug; reduces exposure rate. Needs monitoring.

**Risk if we get this wrong:**
- Model overuses `write_file` for every trivial file operation and burns turns. Mitigation: the prompt wording says "when writing substantial code (>30 lines)"; short edits still go through `file_edit`.
- `python`/`r` tools' timeouts need to be independent of the overall `model_timeout_sec`. The `timeout` parameter in the tool schema is the per-tool execution cap, distinct from the chat call budget. Already distinguished in `_bash`.

## Sequencing relative to other work

1. **Blocker:** wait for the 2026-04-23 full benchmark to complete. Cross-hash attribution.
2. **Land this change.** Re-run the full benchmark — the new prompt_hash's lift is the attribution signal.
3. **Then:** the upstream work (file #21384 with reproducer; wire `llguidance`).
4. **Then:** AutoResearch prompt iteration proper.

## Out of scope

- Fixing the parser bug in llama.cpp itself. Separate workstream.
- Grammar-constrained generation (`llguidance`). Already designed, defer.
- Adding more exotic tools (`sql(query)`, `jq(expr)`, etc.). Only add if concrete evidence they're needed.
- Swapping to a different inference stack. Explicit non-goal per remediation plan.
