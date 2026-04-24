# Analysis — `unknown_zero` failure-mode characterization (2026-04-24)

## Purpose

v3 benchmark ended at **27/89 Pass@1**, with `unknown_zero = 30` as the dominant non-success bucket. This doc inspects 5 sampled trajectories to characterize *why* those 30 trials failed, and maps the categories to concrete prompt/harness interventions.

The goal is to inform the first real AutoResearch iteration. A single "make the prompt better" edit won't fix 30 diverse failures; different failure shapes need different interventions.

## Sample

Five `unknown_zero` trials picked across the turn-count spread (1, 6, 12, 24, 36). All five are from job `full_benchmark_2026-04-23__13-44-54` under `prompt_hash d01537e08c50aaf7`.

| Task | Turns | Tool calls | Summary |
|---|---|---|---|
| `circuit-fibsqrt` | 1 | 1× file_view | Agent viewed `/app/sim.c` and quit. No attempt. |
| `sanitize-git-repo` | 6 | 6× bash | Grepped for 5 different API-key patterns. Found none. Never attempted to replace anything. |
| `break-filter-js-from-html` | 12 | 3× write_file, 7× bash, 2× file_view | Tried three XSS vectors (SVG animate, img onerror, meta refresh). All filtered. Model noted "didn't trigger alert" after each but ran out of ideas. |
| `sparql-university` | 24 | 3× write_file, 20× bash, 1× file_view | Wrote a complex SPARQL query 3 times, verified graph structure by grepping, ended with confident summary of what query does. Reward 0 = query result didn't match expected. |
| `git-multibranch` | 36 | ~8× write_file, ~28× bash | Full server setup: git user + SSH password auth + nginx + SSL cert + post-receive hook. Confirmed "all services running" at end. Reward 0 = something about the grader's test sequence failed. |

## Failure-mode taxonomy

Four distinct shapes observed in 5 samples:

### Mode 1: Early giveup (1 task)

**Example:** `circuit-fibsqrt`.

Agent makes one probe (`file_view`), produces no visible reasoning, and the loop exits with `finish_reason=stop` after that single turn. Trial budget is 40 turns; agent used 1.

**Hypothesis:** the task's complexity is intimidating (implement floor(sqrt(fib(n))) using only gates.txt) and the model's thinking either reasoned its way to "I can't" or got truncated.

**Lever:** anti-giveup prompt nudge. Current `prompts/system.md` has a "Turn budget discipline" section but it's permissive — it tells the model to submit minimal rather than explore more. May need to flip the default: **never exit before turn 5 unless a grader-checkable artifact exists**.

**Estimated share of the 30 unknown_zero:** ~3-5 tasks (low-turn tail).

### Mode 2: Explore without complete (1 task)

**Example:** `sanitize-git-repo`.

Agent ran multiple `grep -rn` calls for API-key patterns. Didn't find many matches (the task seeds fake keys that don't match real-world regex patterns). Never pivoted to "let me look at what IS in the repo that might be a key in disguise." Never performed any edits. Terminated early.

**Hypothesis:** the model's exploration strategy hit a dead end and it didn't adapt.

**Lever:** "complete the task" discipline. Add to prompt: **if your exploration strategy returns empty results, change strategy — don't stop exploring.** Also: force a "what I did" summary turn that specifically asks "have I produced the artifact the grader checks?"

**Estimated share:** ~5-8 tasks (tasks with moderate turn counts that end with 0 passes despite apparent effort).

### Mode 3: Capability ceiling (1 task)

**Example:** `break-filter-js-from-html`.

Agent tried three reasonable XSS bypass techniques. The task filter is specifically designed to block common ones. Getting past it requires either obscure CSP-escape tricks or specific vulnerability-research knowledge the model doesn't reliably have.

**Hypothesis:** genuine knowledge gap. 3B-active MoE doesn't encode the full XSS-vector tree.

**Lever:** **no prompt fix available.** This is the "we won't solve this without a larger model or fine-tuning" class. Accept, move on.

**Estimated share:** ~8-12 tasks — mostly the harder domain-specific ones (path-tracing, schemelike-metacircular-eval, cryptanalysis tasks, etc.).

### Mode 4: Close but wrong (2 tasks)

**Examples:** `sparql-university`, `git-multibranch`.

Both did extensive real work. Both ended with confident summaries of what they'd built. Both scored 0. In each case, some subtle grader-visible detail was wrong — probably a filter criterion or an SSH config parameter that doesn't match the grader's check exactly.

**Hypothesis:** the agent doesn't verify against the *exact* grader check before submitting. It verifies its own sense of what the task asked for. Those two diverge on edge cases.

**Lever:** **forced self-verification**. Before the final message, require the agent to: (a) list the grader-checkable artifacts/behaviors, (b) run them itself, (c) report the results. Failing self-verification → go back to work. Passing → submit.

This is structurally the same pattern as a test-driven-development discipline. The `TOOLS_WORKSHOP_2026-04-23.md` doc already flagged "self-review turn before completion" as a prompt-level improvement (T2).

**Estimated share:** ~8-12 tasks — the ones that used 15-40 turns of real work and still ended at 0.

## Mapping: the 30 unknown_zero tasks by likely mode

Rough classification from task-type and turn-count patterns (actual sample is 5/30):

| Mode | Est. count | Shape | Lever | Expected payoff |
|---|---|---|---|---|
| 1. Early giveup | 3-5 | turns ≤ 5 | anti-giveup prompt | marginal (2-3 recovered) |
| 2. Explore-without-complete | 5-8 | turns 5-15, low tool diversity | "complete the task" discipline | moderate (3-5 recovered) |
| 3. Capability ceiling | 8-12 | any turn count, domain-specific | none | 0 |
| 4. Close but wrong | 8-12 | turns 15+, high tool-diversity | forced self-verification | **biggest lift — 5-8 recovered** |

**Total realistic recovery from prompt work: ~10-15 of 30.** Enough to lift Pass@1 from 27/89 to 35-40/89 if the interventions land.

## Recommended next prompt iteration

One edit to `prompts/system.md`, new `prompt_hash`. Targets Modes 1, 2, 4 simultaneously. Can't help Mode 3.

Proposed addition to the "Completion" section of `prompts/system.md`:

```
# Self-verification before completion

Before you emit your final content-only message ending the trial:

1. **Re-read the task instruction.** What exact files, commands, or behaviours does the grader check?
2. **Verify each grader-checkable artifact exists and has the right shape.** Use file_view, bash ls, or actually run the command the grader will run.
3. **If any check fails, go back to work.** Do not emit a "I'm done" message until every checkable item has been verified to pass.
4. **If your verification reveals a problem you cannot fix, say so explicitly** in your final content. Do not claim success you haven't verified.

Do not describe what you built. Describe what you verified.

# Don't give up early

If you have used fewer than 5 turns and have not produced a grader-checkable artifact, continue working. The task is always harder than it looks in the first probe. Silence and early exit is the worst failure mode.

# Exploration that returns empty

If an exploration strategy (grep, find, ls) returns no matches, that is information, not a dead end. Change your search terms, look at what IS present instead of what you expected, or re-read the task for hints about where the relevant content actually lives.
```

## Next actions

1. **Land this as a prompt iteration.** Single variable change. New `prompt_hash`.
2. **Re-run EASY_SUBSET** to check no regression on the 3 passing tasks.
3. **Re-run full 89-task benchmark** under new prompt — target metric: **Pass@1 ≥ 32/89** (recover 5 of 30 unknown_zero).
4. **If successful, promote** — this is the first real AutoResearch-style iteration that moved a number.

## Methodological note

This analysis is based on 5/30 sampled trajectories. The mode-share estimates are not rigorous. A proper sample would inspect all 30. But 5 is enough to see that the bucket is heterogeneous and that Mode 4 is the biggest single target. The estimates above are useful for priority, not for confidence intervals.

A later AutoResearch iteration could classify all 30 automatically (e.g. "did the last turn produce an assistant message claiming success?" → candidate Mode 4) and track per-mode recovery rates across prompt variants. That's the substrate the fast-eval-proxy design doc will eventually formalize.

## References

- `docs/TOOLS_WORKSHOP_2026-04-23.md` — the "self-review turn" suggestion (T2 in cross-cutting improvements)
- `docs/Design 2026 04 22 fast eval proxy · MD` — tiered eval + structured-reflection framing
- `runs/ledger.jsonl` — v3 failure_tag distribution
- `jobs/full_benchmark_2026-04-23__13-44-54/` — trial traces inspected
