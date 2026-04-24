# Design — MINI_SET calibrated 20-task inner-loop benchmark (2026-04-24)

## Purpose

Full Terminal-Bench 2 takes ~24h per run. At that cost, AutoResearch iteration is infeasible — we can't A/B prompt variants. The fast-eval-proxy design doc (Track 3) calls for a calibrated subset that reproduces ranking information from the full set at a fraction of the cost.

`MINI_SET` in `eval/subsets.py` is our first cut at this. 20 tasks, expected ~2-3h wall time at current config — **~10× speedup over the full benchmark**.

## Selection methodology

Classical IRT-based subset selection (tinyBenchmarks, metabench) requires pass/fail data from many models. We only have one: Qwen3.6. So IRT isn't available to us. Instead, we use **v1-vs-v3 pass pattern** as a proxy for task discriminativeness.

We have two full-89 runs under the same backbone but different scaffold versions:
- v1 (prompt_hash `d41e9732`): 17/89 passes. Bash-only tools, 20-turn budget.
- v3 (prompt_hash `d01537e08c50aaf7`): 27/89 passes. Plus write_file/python/r, 40-turn budget.

Tasks partition into six categories by (v1_pass, v3_pass, v3_failure_tag):

| Category | Count | Meaning | Role in MINI_SET |
|---|---|---|---|
| both_pass | 13 | Reliable across both scaffolds | Regression sentinel — always should pass |
| v3_only_pass | 14 | Recovered by v3 tool expansion | Confirms scaffold gains held |
| v1_only_pass | 4 | Broken by v3 (regression) | Regression sentinel — something in v3 hurt these |
| fail_unknown_zero | 27 | Silent fail — model ran, didn't solve | Prompt-tuning target |
| fail_turn_exhaustion | 19 | Ran out of turns | Hard tail, controls for budget experiments |
| fail_infra | 12 | model_timeout / server_bad_request / AgentTimeout | Sanity for harness edge cases |

The MINI_SET picks a stratified sample from each category. Quotas:

| Category | MINI_SET quota | Why |
|---|---|---|
| both_pass | 5 | Regression detection needs enough reliable cases |
| v3_only_pass | 5 | Confirms tool-expansion is still helping |
| v1_only_pass | 3 | Detects new regressions |
| fail_unknown_zero | 4 | The target class for AutoResearch |
| fail_turn_exhaustion | 2 | Watch the hard tail |
| fail_infra | 1 | Harness health signal |
| **total** | **20** | |

Within each category, we pick by even sampling of v3 turn counts — gives a spread of fast/slow cases rather than all the same shape.

## What MINI_SET is good for

- **A/B prompt variants** in ~2-3h wall each instead of 24h.
- **Regression detection** — if both_pass / v3_only_pass bins drop in pass rate, something broke.
- **Prompt-tuning feedback** — the 4 fail_unknown_zero tasks tell us whether a prompt change actually converts any of that bucket.
- **Inner-loop fitness signal** for a future optimizer — scored and tagged consistently with the full benchmark.

## What MINI_SET is NOT good for

- **Absolute Pass@1 numbers** — it's a biased sample; 20-task results don't directly extrapolate to 89. Use for *ranking* between configurations, not absolute claims.
- **Ranking preservation at the top-tier** — if a future iteration pushes pass rate toward 0.5+, the mini-set's discriminability weakens (Perlitz et al. on BAT protocol; see fast-eval-proxy doc). Monitor: if MINI_SET/full correlation drops below Spearman 0.7, rebuild.
- **New task categories** — only tests variants of scaffold behaviour that existed in v1 or v3. Truly new failure modes in future iterations may not be covered.

## Expected MINI_SET pass rate on v3 prompt

Based on the v3 full-benchmark data:

| Category | Count | v3 pass rate | Expected passes |
|---|---|---|---|
| both_pass | 5 | 13/13 = 100% | **5** |
| v3_only_pass | 5 | 14/14 = 100% | **5** |
| v1_only_pass | 3 | 0/4 = 0% | 0 |
| fail_unknown_zero | 4 | 0/27 = 0% | 0 |
| fail_turn_exhaustion | 2 | 0/19 = 0% | 0 |
| fail_infra | 1 | 0/12 = 0% | 0 |
| **v3 baseline on MINI_SET** | 20 | | **10 / 20 = 0.500** |

So the expected v3 baseline on MINI_SET is **10/20 = 0.500**.

The full-benchmark v3 is 27/89 = 0.303. The MINI_SET is biased toward the passing bins (10/13 of the both_pass + v3_only_pass rows fit inside) — so absolute numbers don't map directly to the full set. But relative lift across iterations should track.

## Acceptance criteria for the first MINI_SET run under prompt v4

Prompt v4 showed 1/6 conversion on a targeted re-run. Extrapolating, we'd expect on MINI_SET:

- both_pass: 5 (unchanged)
- v3_only_pass: 5 (unchanged, or −1 if noise like openssl regressed)
- v1_only_pass: 0-1 (one of these might re-pass under v4)
- fail_unknown_zero: 0-1 (v4's primary target)
- fail_turn_exhaustion: 0
- fail_infra: 0
- **v4 target on MINI_SET: 10-12 / 20**

That range is meaningful. If v4 comes in at ≥12/20 on MINI_SET, it's a clear win worth promoting. If 10-11, roughly neutral. If ≤9, v4 is regressing.

## Running the mini-set

```bash
bash scripts/mini_set.sh
# outputs: jobs/mini_set_<timestamp>/ and appends ledger rows with job_name starting "mini_set_"
```

## Evolution plan

- **Now:** ship this 20-task MINI_SET, use for next N iterations.
- **After 3-5 iterations:** compare MINI_SET scores against the last full-89 benchmark under each prompt_hash. Calculate Spearman correlation of task-level ranks between MINI_SET and full. If >0.7, the proxy is working. If <0.7, rebuild with different selection.
- **After we have 5+ prompt_hashes with both MINI_SET and full-89 data:** proper IRT-style item selection becomes possible. Swap in a version built from actual multi-config data.
- **Long term:** merge with Hobbhahn-style distribution-matching and Aider-style repo-map mechanisms (see `TOOLS_WORKSHOP_2026-04-23.md` Appendix A/B).

## Files shipped

- `eval/subsets.py` — `MINI_SET` (and unchanged `EASY_SUBSET`)
- `scripts/mini_set.sh` — runner that reads MINI_SET and calls Harbor
- `docs/DESIGN_2026-04-24_mini_set.md` — this file

## Out of scope

- Execution-free L1 reward. Requires TB2 verifier introspection that's not available in-band. Deferred.
- Sacred held-out set. Should be 5-10 tasks NEVER in MINI_SET or L1 calibration. Pick after we've run MINI_SET a few times and know which tasks are truly stable discriminators.
- Drift monitor. Build once we have MINI_SET + full data across multiple iterations.
