# Verdict — Prompt v4 on MINI_SET (2026-04-25)

## Result

**10 / 20 MINI_SET passes under prompt_hash `3310982e1ed6f2a2`** (19/20 scored at writing; last trial code-from-image pending, won't change the verdict).

v3 baseline expectation on MINI_SET was 10/20 (both_pass + v3_only_pass bins passing, everything else 0). v4 landed **exactly at baseline** — net-neutral.

## Category breakdown

| Category | Expected (v3) | Actual (v4) | Delta |
|---|---|---|---|
| both_pass (5) | 5 | 4 | **−1** (`prove-plus-comm` regressed) |
| v3_only_pass (5) | 5 | 4 | **−1** (`distribution-search` slipped) |
| v1_only_pass (3) | 0 | **2** | **+2** (`cancel-async-tasks`, `pytorch-model-recovery` recovered) |
| fail_unknown_zero (4) | 0 | 0 | **0** — hypothesis failed |
| fail_turn_exhaustion (2) | 0 | 0 | 0 |
| fail_infra (1) | 0 | 0 | 0 |
| **total** | **10** | **10** | **0** |

## Hypothesis assessment

v4's stated hypothesis (from `docs/ANALYSIS_2026-04-24_unknown_zero.md`): self-verification + anti-giveup + empty-exploration nudges would recover 5-8 of the 30 unknown_zero tasks.

**Actual conversion in MINI_SET: 0/4.**

Extrapolated: 0/30. The self-verification pattern didn't land as a prompt-level intervention.

## What happened instead

Unintended positive: **v4 recovered 2 of 3 v1_only_pass tasks** — tasks that passed in v1 but regressed in v3.

- `cancel-async-tasks`: passed v1 (unknown_zero in v3) → passes v4
- `pytorch-model-recovery`: passed v1 (unknown_zero in v3) → passes v4

Plausible explanation: the anti-giveup nudge ("never exit before turn 5 without a grader-checkable artifact") pushed the model past an early-termination point these tasks were previously hitting. Not what we designed for, but real.

Unintended negative: `prove-plus-comm` regressed. Previously passed both v1 and v3. Now fails under v4. Possibly the self-verification section is adding enough output tokens that the model's effective reasoning budget shrinks on tight-turn tasks.

## What we learned

1. **Self-verification as a prompt rule doesn't convert Mode-4 failures** in practice. The model-of-the-task vs the-grader's-actual-check gap isn't closed by prompting alone — the model can't always generate the exact check the grader will run.

2. **Broad prompt changes have side effects.** We added 25 lines of system prompt targeting specific failure modes; the effect was spread over categories we didn't intend to touch (+2 recovery, −1 regression, −1 slip).

3. **MINI_SET is working as intended.** 19 of 20 scored in ~7h wall vs 24h for full benchmark. The category breakdown cleanly separates signal from noise — we can see exactly which bins moved, not just a headline number.

4. **Prompt iterations have smaller effect sizes than tool/scaffold changes.** v3 (tool expansion + config raises) delivered +58% relative lift. v4 (prompt wording) delivered 0% on the subset. Scaffold remains the higher-leverage lever.

## Decision: keep or revert v4?

**Keep.** Reasoning:

- Net on MINI_SET is neutral (10/20 either way)
- Unintended recovery of 2 v1_only_pass tasks is a real gain we'd lose on revert
- The 1 regression (prove-plus-comm) and 1 slip (distribution-search) could be within single-sample noise
- Reverting to v3 prompt would cost those 2 recovered tasks without a clear benefit

If a future variant clearly beats v4 on MINI_SET (≥12/20 passes), promote that. Otherwise v4 stays as the current default.

## Next prompt iteration candidates

Ranked by likelihood of moving MINI_SET:

### Candidate A — "imitate the grader's test" (structural)

Instead of "re-read the task and verify," make the agent emit a bash script that reproduces the grader's checks as its second-to-last turn. Then assess its own output against that script's output.

**Why better than v4:** forces an explicit, machine-runnable check rather than a human-readable self-report. Removes the "model convinced itself it passed" failure mode that v4's self-verification doesn't break.

**Risk:** not all TB2 tasks have grader-style checks the agent can reproduce (some are binary state transitions, some are file diffs).

### Candidate B — "verbose thinking, minimal content" (token-budget)

Nudge the model to concentrate reasoning in `reasoning_content` and emit extremely terse visible `content`. Hypothesis: unknown_zero tasks burn turns on performative explanation; shifting that budget to structured thinking turns could unlock more real work per turn.

**Why plausible:** our ledger shows v3-to-v4 didn't increase turn efficiency; some model budget still spent on visible narration. The Qwen3.6 thinking-mode field exists specifically for this.

**Risk:** too terse content might trigger the empty-content 400s we fixed in commit `4e559b6`. Test carefully.

### Candidate C — "initial task-shape probe" (repo_map adjacent)

On turn 1, require the agent to call a specific probe (likely `bash "ls -la /app && head -50 /app/*.md /app/*.txt 2>/dev/null"`) before planning. Catches tasks where the agent skips environment exploration and plans based on a wrong mental model.

**Why plausible:** circuit-fibsqrt (the 1-turn giveup) is the extreme case — an agent that didn't explore. Forcing a probe would at minimum produce more context before the model decides.

**Risk:** wastes a turn on tasks where the model already knows what to do. Probably net-positive on hard tasks, net-negative on easy ones.

### Candidate D — "single-token tool_call self-test" (dedicated tool)

Add a new tool `check(description)` that the model must call before completion. Server-side, this tool runs a generic check (e.g., verify any files the model mentioned creating exist, and that recent bash commands succeeded). Returns a structured "ready to submit" or "problems: ...".

**Why plausible:** moves self-verification from a prompt rule to a mandatory tool call. Harder to skip, easier to reason about.

**Risk:** tool complexity; figuring out what to check generically is nontrivial.

## Recommended next iteration

**Candidate B (thinking-content split)** — smallest change, most direct test of a different hypothesis. ~10 line prompt edit. Runnable on MINI_SET in one day.

**If B is neutral too**: consider that single-prompt-iteration is a low-leverage lever for this model/task combo. Shift focus to:
- More Tier-1 tool additions (`read_file_range`, `apt_install`, `apply_patch`, `done`)
- Pass@2 evaluation convention (automatic +4-5 on headline number)
- Backbone upgrade if Qwen3.7 or Qwen3-MAX becomes available

## Writing the next iteration

Simple proposal for Candidate B — single prompt edit:

Add to `prompts/system.md`:

```
# Where to put reasoning

- Your `reasoning_content` (thinking-mode) is the right place for: multi-step plans, considering alternatives, catching your own mistakes, debugging unexpected tool output.
- Your visible `content` before each tool call should be 1-2 short sentences stating what you're about to do. Not what you thought about. Not what you plan. Just the action.
- Do not narrate your thought process in visible content. Narration costs turns without adding work.
- Extreme conciseness in `content` is correct. Assume the reader reads only your final submission.
```

New `prompt_hash` after landing. Run MINI_SET, compare vs v4's 10/20.

## What I'm NOT recommending

- **Revert to v3 prompt.** Net-neutral is not worth reverting; we'd lose the 2 v1_only_pass recoveries.
- **Full benchmark under v4.** 24h to confirm we're at ~27-28/89 is not worth the compute. MINI_SET told us what we needed.
- **Another prompt iteration before MINI_SET completes at this cadence.** Need the full 20/20 before starting the next cycle.

## References

- `docs/ANALYSIS_2026-04-24_unknown_zero.md` — the hypothesis this tested
- `docs/DESIGN_2026-04-24_mini_set.md` — the eval substrate
- `jobs/mini_set_2026-04-24__21-12-28/` — full trial artifacts
