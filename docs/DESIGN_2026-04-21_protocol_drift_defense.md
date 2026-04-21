# Design — Defensive handling for Gemma protocol drift (2026-04-21)

## Problem

See `docs/OBSERVED_ISSUE_2026-04-21_MODEL_PROTOCOL_DRIFT.md` for the full evidence. In short: on harder Terminal-Bench 2 tasks Gemma sometimes emits pseudo-markup (`<|channel>thought`, `<|tool_call>call:bash{…}<tool_call|>`, etc.) in the assistant `content` field. That markup is structurally valid for the response, but when the harness appends the assistant message to `messages` and fires the next request, the llama.cpp OpenAI-compatible server fails to parse it and returns HTTP 500 `InternalServerError`. The trial then aborts before verifier evaluation.

This is a **distinct** failure mode from the earlier Harbor / cwd / timeout bugs. It is not solved by prompt tightening alone — prompt changes help but cannot guarantee a small model won't occasionally drift.

## Goal

Make drift **observable**, **attributable**, and **recoverable for isolated slips**, while failing fast on runs that drift repeatedly.

## Options considered

| # | Option | Verdict |
|---|---|---|
| A | Silent strip of pseudo-markup from `content` | Too permissive — loses attribution |
| B | Detect-and-abort on first drift | Too strict — kills trials that would have recovered |
| C | Detect + sanitize + inject corrective note | Too clever — adds message shape the model hasn't seen in training |
| D | Parse the garbled markup as a real tool call | Rewards bad behaviour; markup quoting is fragile |
| E | Switch llama.cpp thinking mode off | Parallel investigation, not a defensive fix |
| **F** | **Sanitize + count, fail on repeat (A+B hybrid)** | **Chosen** |

## Decision: Option F

1. Sanitize known pseudo-markup from `content` before appending to history.
2. Tag the trace entry with `protocol_drift=True` whenever sanitization stripped anything.
3. Maintain a per-trial drift counter. If `drift_count >= 2` in one trial, abort with `status="malformed_model_output"`.
4. Record `malformed_model_output` as a first-class `failure_tag` in `runs/ledger.jsonl`.

### Why F over the alternatives

- We know Gemma *can* stay clean — `fix-git` passed under the current `prompt_hash`. A single-turn slip doesn't mean the whole trial is lost; forgiving it preserves potentially-winning runs.
- Silent sanitization (A) hides the signal. AutoResearch needs per-`prompt_hash` drift rates to attribute which prompt changes reduce drift.
- One-strike-out (B) discards trials cheaply. Two strikes is a compromise that still prevents unbounded cascades.
- Injecting corrective messages (C) adds conversational shapes Gemma has no prior exposure to, and the reaction is unpredictable. Worse, it adds complexity we'd need to reason about when debugging future iterations.
- Parsing the garbage markup (D) welds the harness to a specific failure shape that is likely to shift across model versions.

## Interface

### New function in `harness/harness.py`

```
def sanitize_assistant_content(msg_dict: dict) -> tuple[dict, bool]:
    """
    Strip known Gemma protocol-drift markup from the `content` field of an
    assistant message. Returns (cleaned_msg, drift_detected).

    Drift patterns (compiled once):
      <|channel>   <channel|>
      <|tool_call> <tool_call|>
      <|thought>   <thought|>
      <|"|>         (pseudo-quote used inside the drift markup)
      other pipe-angle-bracket tokens matching <\|[^|>]+\|?> or <[^|>]+\|>

    Structured tool_calls on the message are NOT touched.
    """
```

### Changes in `run_agent`

- Immediately after `msg_dict.pop("reasoning_content", None)`, call `sanitize_assistant_content`
- If `drift_detected`:
  - Stamp the trace row with `protocol_drift=True`
  - Increment `drift_count`
  - If `drift_count >= 2` → return `{"status": "malformed_model_output", "turns": turn, "trace": messages, "drift_count": drift_count}`
- On normal return (success or turn_limit), include `drift_count` in the result dict so the ledger can see single-slip trials

### Changes in `scripts/record_baseline.py`

- Extend `tag_failure(...)` so that any trial whose `gemma_result.status == "malformed_model_output"` returns `"malformed_model_output"` — ahead of the other checks.
- Add `drift_count` to the ledger row schema.

## What the ledger will show

Each row gains one field:

```
"drift_count": 0    # clean trial
"drift_count": 1    # one-turn slip, recovered, ran to completion
"drift_count": 2    # aborted — failure_tag = malformed_model_output
```

This lets us track drift-rate-per-prompt_hash as a first-class AutoResearch signal alongside reward.

## Validation plan

1. **Re-run** the validation on `terminal-bench/make-mips-interpreter` (the task that triggered the 500).
2. **Expected new outcome:** no HTTP 500. Trial either completes with `drift_count >= 1` logged per turn, or aborts cleanly with `failure_tag = malformed_model_output`.
3. **Re-run the full baseline** on EASY_SUBSET. Confirm `fix-git` still passes under the new code path — i.e. the sanitizer doesn't regress clean trials.
4. **Compare drift rate across prompt_hashes.** Record in the gemma-agent `memory/learnings.md`.

## Follow-up: Option E as a parallel investigation

After F is in place and has produced drift-rate data, run a diagnostic: toggle llama.cpp thinking mode off and re-run EASY_SUBSET. If drift rate drops meaningfully with no regression in reward, prefer thinking-off as the default and keep F as belt-and-braces.

This is **not** part of the F landing — it's a follow-up experiment that depends on F's instrumentation being in place.

## Non-goals

- This change does **not** attempt to improve task-solving behaviour. Its only job is to stop pseudo-markup from taking down trials and to surface drift as a measurable quantity.
- This change does **not** alter prompt/skill/policy content. Prompt tightening against drift is a separate lever and belongs in a later iteration.

## Governance

`harness/*` is officially locked in Phase 1. This change is explicitly unlocked for this work because:

1. The issue's consultant note specifically recommended defensive harness-side handling
2. The alternative (prompt-only mitigation) was explicitly rejected as insufficient
3. The change is strictly additive — it does not alter the execution path of a clean trial, only intercepts a failure that would otherwise crash

A handoff note will accompany the patch: `~/.openclaw/workspace/handoffs/gemma-harness-protocol-drift-defense-2026-04-21.md`.
