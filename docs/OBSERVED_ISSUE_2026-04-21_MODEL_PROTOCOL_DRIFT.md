# Observed Issue — Model protocol drift on hard tasks (2026-04-21)

## Summary
During post-baseline validation of `gemma-harness`, a distinct failure mode was observed on harder Terminal-Bench 2 tasks:

> Gemma emits malformed pseudo-protocol markup such as `<|channel>thought` and `<|tool_call>...` instead of producing a clean assistant response and valid structured tool calls.

This causes the OpenAI-compatible llama.cpp server to fail parsing the request/response sequence and return an HTTP 500 `InternalServerError`.

This is now a confirmed issue and should be treated as a separate failure mode from:
- Harbor integration bugs
- working-directory bugs
- dataset/subset mismatches
- long opaque Harbor-level timeouts

---

## Context
Recent work established that:
- Harbor is installed and functioning
- Terminal-Bench 2 dataset path is correct
- `gemma-harness` runs as a Harbor BaseAgent
- tool execution works
- prompt cleanup improved behavior enough to produce a non-zero baseline on `fix-git`
- per-call model timeout handling was added to prevent one slow Gemma response from consuming the full Harbor trial budget

After that timeout fix, validation was re-run against:
- `terminal-bench/make-mips-interpreter`

Validation job:
- `jobs/2026-04-21__15-05-02`

---

## What happened
The run no longer hung for the full Harbor timeout window. Instead, it failed quickly with a server-side parse error.

### Observed outcome
Top-level result:
- `n_trials = 1`
- `n_errors = 1`
- exception type: `InternalServerError`

Trial:
- `make-mips-interpreter__CupHwtC`

### Key error
The OpenAI-compatible server returned:

```text
Error code: 500 - Failed to parse input at pos 56:
<|channel>thought
<channel|><thought
...
<|tool_call>call:bash{cmd:<|"|>objdump -d doomgeneric_mips | head -n 50<|"|>}<tool_call|>
```

---

## Interpretation
This is not primarily a Harbor problem.
This is not primarily a task-subset naming problem.
This is not the same as the earlier 900-second opaque timeout problem.

This is a **model output protocol drift** problem.

On harder tasks, Gemma sometimes stops following the intended structured tool-calling protocol and instead emits internal-looking markup resembling:
- channel tags
- thought tags
- pseudo tool-call syntax

That malformed output is incompatible with the server/parser path and causes a hard 500.

---

## Why this matters
This failure mode is important because it can masquerade as a general infrastructure problem while actually being a specific model-behavior issue.

Without calling it out explicitly, future debugging could incorrectly conclude that:
- the timeout patch failed
- the server is unstable in general
- the task itself is solely responsible

But the observed evidence shows something narrower:

> The timeout patch improved observability and prevented long silent stalls, but the validation still fails because Gemma is emitting malformed protocol text on difficult tasks.

---

## What the timeout patch *did* accomplish
The timeout patch should still be considered useful.

### Before
A single Gemma request could appear to consume most or all of the Harbor trial budget, resulting in a slow opaque failure.

### After
The failure surfaced much faster, making the next blocker visible.

So the timeout patch improved the system in this sense:
- faster failure
- clearer diagnosis
- less wasted wall-clock time

However, it did **not** resolve the protocol-drift problem.

---

## Current classification
Recommended classification for this failure mode:

**Failure class:** `model_protocol_drift`

Suggested meaning:
- The model emitted malformed pseudo-protocol / pseudo-tool-call text instead of valid structured tool use.
- The server or client layer could not parse it cleanly.
- The run failed before meaningful verifier evaluation.

---

## Recommended next step
The next engineering slice should target defensive handling of malformed model output.

### Recommended direction
Add harness-side protection so that known-bad protocol patterns are detected and handled explicitly.

Examples of problematic strings/patterns:
- `<|channel>`
- `<channel|>`
- `<|tool_call>`
- `<tool_call|>`
- similar pseudo-internal markup emitted in assistant content

### Preferred behavior
Instead of allowing these to propagate into a server-side 500, the harness should:
- detect them
- classify them as malformed model output
- fail the run or turn in a controlled, explicit way

This would turn a vague infrastructure-looking error into a clean benchmark artifact with a known cause.

---

## Suggested follow-up work
1. Add harness-side detection for malformed pseudo-protocol strings
2. Return a controlled error/result such as:
   - `status: malformed_model_output`
3. Re-run the same validation task
4. Confirm that the new result surface is:
   - faster
   - cleaner
   - easier to reason about than a raw 500

Optional later step:
- tighten prompt wording further to discourage channel/tool-call pseudo-markup

But prompt-only mitigation should not be relied on as the sole fix.

---

## Bottom line
Observed issue:

> On harder tasks, Gemma can drift into malformed internal/pseudo tool-call markup (`<|channel>`, `<|tool_call>`, etc.), which causes the llama.cpp OpenAI-compatible server to return `InternalServerError` instead of producing a valid tool-using agent turn.

This is now a documented and distinct failure mode in `gemma-harness`.
