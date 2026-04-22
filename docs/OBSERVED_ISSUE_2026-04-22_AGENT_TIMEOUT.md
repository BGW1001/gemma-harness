# Observed Issue: AgentTimeoutError on EASY_SUBSET (2026-04-22)

## Summary

`openssl-selfsigned-cert` and `sanitize-git-repo` have been scoring 0.0 on every
run. Root cause: **Harbor's hard 900-second (15 min) agent timeout is hit before
the agent finishes**, not because the task is too hard or the prompt is wrong.

`fix-git` also had one HTTP 500 trial (separate bug — see
`OBSERVED_ISSUE_2026-04-21_MODEL_PROTOCOL_DRIFT.md`), but the two trials that
completed did so in 105s and 559s respectively, both under the limit.

## Evidence

From `jobs/baseline_2026-04-21__12-09-05`:

| Trial | Duration | exception_type | reward |
|---|---|---|---|
| openssl-selfsigned-cert__NDHfq5Z | 926s | AgentTimeoutError | 0.0 |
| openssl-selfsigned-cert__dAtju6R | 926s | AgentTimeoutError | 0.0 |
| openssl-selfsigned-cert__iF6VVjn | 926s | AgentTimeoutError | 0.0 |
| sanitize-git-repo__H4fnvTy | 926s | AgentTimeoutError | 0.0 |
| sanitize-git-repo__aKqvCCo | 924s | AgentTimeoutError | 0.0 |
| sanitize-git-repo__vXzjmF9 | 926s | AgentTimeoutError | 0.0 |
| fix-git__XVpzd9J | 346s | InternalServerError (500) | — |
| fix-git__Lq6bjNT | 105s | none | 1.0 |
| fix-git__vTQAtou | 559s | none | 1.0 |

All 6 non-fix-git trials terminated at exactly the 900s boundary with
`AgentTimeoutError: Agent execution timed out after 900.0 seconds`. The
`verifier_result.rewards.reward` and `agent_result.metadata.gemma_result` are
both null when this happens — Harbor kills the agent before it can write a result.

## Root cause analysis

The base agent timeout in `task.toml` for all three EASY_SUBSET tasks:
```
[agent]
timeout_sec = 900.0
```

The server is running CPU-only (ROCm/HIP init failed). Observed turn latency:
- `fix-git__Lq6bjNT`: 105s / 9 turns = **11.7s/turn** (fast, likely cached)
- `fix-git__vTQAtou`: 559s / 11 turns = **50.8s/turn** (slow, no cache)

At 50s/turn with `max_turns=40`, theoretical maximum is **2000s** — more than
twice the 900s limit. The model was still actively running (not stuck), it just
didn't finish in time.

The prior `config.yaml` had `max_turns: 40`, which is fine for GPU-served models
(~2-5s/turn → well under 900s) but catastrophic on CPU-only.

This was masked by the fact that `fix-git` tends to complete early (≤11 turns),
while `openssl-selfsigned-cert` likely needs 12-20 turns to complete all the
certificate steps.

## Fix applied (2026-04-22)

### 1. `config.yaml`: reduce `max_turns` from 40 → 20
All three fix-git wins happened in ≤11 turns, so 20 is generous.
At 50s/turn × 20 turns = 1000s — still over the 900s base, hence fix #2.

### 2. `scripts/baseline.sh`: add `--agent-timeout-multiplier 3.0`
Effective limit becomes 900s × 3.0 = **2700s** (45 min) per trial.
At 50s/turn × 20 turns = 1000s — safely under 2700s.

Env override: `AGENT_TIMEOUT_MULTIPLIER=5 bash scripts/baseline.sh` for extra headroom.

### 3. `scripts/baseline.sh`: add `--n-concurrent 1`
CPU-only server has a single processing thread (`--threads 1` in the server
start command). Running 4 trials concurrently would serialize at the model,
multiplying effective latency by ~4× and guaranteeing timeouts. Sequential
trials are slower in wall-clock but each trial gets the full model bandwidth.

Env override: `N_CONCURRENT=4 bash scripts/baseline.sh` to restore parallelism
(e.g., if the server is upgraded to GPU-served and turn latency drops).

### 4. `config.yaml`: reduce `model_timeout_sec` from 90 → 60
Per-call cut. Observed median ~12s, 99th ~50s on CPU-only. 60s gives safe
headroom without burning excessive time on pathological calls.

## Expected outcome

With these fixes, `openssl-selfsigned-cert` should be completable within budget:
- Task is a ~10-step procedural recipe (see `solution/solve.sh`)
- Estimated 10-15 turns for a competent model
- 15 turns × 50s/turn = 750s < 2700s effective cap

`sanitize-git-repo` requires more exploration (find secrets, clean git history)
and may still need 15-20 turns. At 50s/turn × 20 turns = 1000s < 2700s.

## What this does NOT fix

- The HTTP 500 on `fix-git__XVpzd9J` — that's the PEG parser bug (#21375)
  in llama-server b8645 without `--jinja`. Requires Track A system-side work.
- Slow turn latency — that requires GPU serving (Track A B.1-B.3).
- The model producing placeholder/fake implementations on hard tasks.

## Commit

Changes in `3f83f06` (repair) + this doc's commit:
- `config.yaml`: max_turns 40→20, model_timeout_sec 90→60
- `scripts/baseline.sh`: --agent-timeout-multiplier 3.0, --n-concurrent 1
- `scripts/validate.sh`: --agent-timeout-multiplier propagated
