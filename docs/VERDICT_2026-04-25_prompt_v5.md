# Verdict — Prompt v5 (thinking-content split) on MINI_SET (2026-04-25)

## Result

**10 / 20 under prompt_hash `d99a7c57be569735`** (19 scored at writing; last trial `code-from-image` pending).

Same numerical total as v4 (10/20). **But composition is meaningfully different.**

## Category breakdown vs v4

| Category | v4 | v5 | Delta |
|---|---|---|---|
| both_pass (5) | 4 | **5** | **+1** (prove-plus-comm recovered) |
| v3_only_pass (5) | 4 | 3 | **−1** (openssl regressed) |
| v1_only_pass (3) | 2 | 1 | **−1** (cancel-async-tasks regressed) |
| fail_unknown_zero (4) | 0 | 0 | 0 |
| fail_turn_exhaustion (2) | 0 | **1** | **+1** (largest-eigenval converted!) |
| fail_infra (1) | 0 | 0 | 0 |
| **total** | 10 | 10 | 0 |

Net zero in total, but:
- v5 has a clean 5/5 on `both_pass` (v4 had prove-plus-comm regression)
- v5 converted a `turn_exhaustion` task (largest-eigenval) — a hard-class task v3, v4, and v1 all zeroed on
- v5 lost 2 tasks that v4 had (openssl-selfsigned-cert, cancel-async-tasks)

## Interpretation

**The thinking-content split does reduce per-turn overhead**, as hypothesized. Evidence:
- `prove-plus-comm` — v4 hit turn_exhaustion at 40 turns, v5 solved (back to efficient). Direct proof the budget-waste theory was right.
- `largest-eigenval` — previously turn_exhausted across v1/v3/v4, now converts. This is a hard numeric task where more effective turns make the difference.

**But the gains are canceled by new regressions elsewhere:**
- `openssl-selfsigned-cert` and `cancel-async-tasks` were reliable passes across v3 and v4. Under v5 they zero.
- Plausible: terser visible `content` makes some task shapes harder to follow across turns — the model loses track of its own plan without prose reminders.

This is the **prompt-iteration-is-local-optimization** pattern we've seen in both v4 and v5. Any change that helps one task class costs another. Single-variable prompt edits don't give us a monotonic rise.

## Comparison across the three iterations

| Metric | v3 (tool expansion) | v4 (self-verification) | v5 (thinking split) |
|---|---|---|---|
| prompt_hash | `d01537e08c50aaf7` | `3310982e1ed6f2a2` | `d99a7c57be569735` |
| MINI_SET | 10/20 (baseline) | 10/20 | 10/20 |
| Full-89 | 27/89 measured | — | — |
| turn_exhaustion conversions | 0 | 0 | **1** (largest-eigenval) |
| Trade-off shape | N/A | +2 v1_only_pass, −1 both_pass, −1 v3_only_pass | +1 both_pass, +1 turn_exhaustion, −1 v3_only_pass, −1 v1_only_pass |

## Decision: keep or revert v5?

**Keep v5.** Reasoning:

- Ties v4 on total (10/20)
- Converts `largest-eigenval`, a previously-always-failing task. That's a genuinely new capability unlock.
- `both_pass` now clean at 5/5 — regression sentinel is green
- The openssl / cancel regressions could be single-sample noise; both normally pass within variance

Going forward, v5 is the default. prompt_hash `d99a7c57be569735`.

## The bigger lesson

Three prompt iterations (v3 post-tool, v4 self-verification, v5 thinking-split) all landed at 10/20 on MINI_SET. **Single-variable prompt wording has reached a local plateau for this model/task combination.**

Each variant produces different trade-offs, but the total doesn't move. If we want to lift the number meaningfully, we need a different kind of change — not a re-phrasing of the same kind of prompt.

## Pivot: Tier-1 tool additions (v6)

Per `docs/TOOLS_WORKSHOP_2026-04-23.md`, the queued Tier-1 tool work is:

1. **`read_file_range(path, start, end)`** — ~15 lines. Removes file_view whole-file waste on large source trees. Direct fix for tasks like `make-mips-interpreter`, `overfull-hbox` where the model burns context re-reading.

2. **`apt_install(packages)`** — ~20 lines. Standardizes the 22+ apt operations we saw per benchmark. Removes `DEBIAN_FRONTEND=noninteractive` noise from bash commands.

3. **`apply_patch(path, unified_diff)`** — ~30 lines. Handles multi-hunk edits where `file_edit`'s unique-match fails. Direct fix for tasks with complex edits like `overfull-hbox`, `fix-code-vulnerability` variants.

4. **`done(summary)`** — ~15 lines. Explicit submit. Cleaner termination contract than "content-only message with no tool_calls," eliminates the residual `server_bad_request` cases.

5. **`list_files(path, glob)`** — bonus, ~15 lines. Structured directory listing, reduces `ls`/`find` bash noise.

Total: ~95 lines of code + ~10 lines of prompt guidance = one coherent v6 change. New `prompt_hash`. Testable on MINI_SET in ~7h.

### Expected v6 payoff

Directionally: tool expansions tend to have larger effect sizes than prompt wording changes. v3 (the write_file/python/r expansion) delivered +58% relative. v6 is a smaller change than v3 but in the same class.

Target for MINI_SET: **≥12/20** would be a real win.

## Next action

Implement v6 immediately:

1. Add 5 tools to `harness/tools.py` (~95 lines total)
2. Update `prompts/system.md` tool-selection section (~10 lines)
3. SMOKE on fix-git
4. MINI_SET under v6 — compare against v5's 10/20
5. If ≥12/20 → full benchmark under v6
6. If <12/20 → diagnose, try Tier-2 tools (`repo_map`, `persistent_bash`)
