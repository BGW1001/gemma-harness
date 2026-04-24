# Terminal-Bench 2 task subsets for the inner evaluation loop.
#
# Three levels, matching the fast-eval-proxy design (docs/Design 2026 04 22
# fast eval proxy · MD):
#
#   EASY_SUBSET (3 tasks, ~30 min):  "get off zero" — confirm nothing regressed
#                                    on the trivial-procedural cases.
#   MINI_SET (20 tasks, ~2-3h):      stratified sample across v1/v3 pass-pattern
#                                    categories. For AutoResearch inner loop.
#   Full 89:                          ground truth, runs only at milestones.

EASY_SUBSET = [
    "terminal-bench/fix-git",                  # 7-line solution: reflog + checkout + merge
    "terminal-bench/openssl-selfsigned-cert",  # ~98-line procedural recipe: openssl commands
    "terminal-bench/sanitize-git-repo",        # moderate but well-scoped: find secret, clean repo
]

# MINI_SET — 20 tasks, calibrated from v1 (17/89) + v3 (27/89) results.
# Selection methodology (see docs/DESIGN_2026-04-24_mini_set.md):
#   Stratified across six categories of v1/v3 pass-pattern. Within each bin,
#   picked by even sampling of v3 turn counts to get a spread of fast/slow
#   solves rather than all the lowest-hanging fruit.
# Distribution:
#    5 both_pass              — reliable passes, regression sentinels
#    5 v3_only_pass           — scaffold-recovered, confirms tool-expansion
#    3 v1_only_pass           — regression sentinels (something in v3 broke these)
#    4 fail_unknown_zero      — prompt-tuning targets
#    2 fail_turn_exhaustion   — hard tasks, should stay failing
#    1 fail_infra             — edge case that exercises harbor path
# Total wall time: expect ~2-3 hours at agent_timeout_multiplier=5.0.
MINI_SET = [
    # Reliable passes (should always pass; fast wins)
    "terminal-bench/modernize-scientific-stack",     # both_pass, v3_turns=6
    "terminal-bench/prove-plus-comm",                # both_pass, v3_turns=7
    "terminal-bench/multi-source-data-merger",       # both_pass, v3_turns=10
    "terminal-bench/pypi-server",                    # both_pass, v3_turns=10
    "terminal-bench/git-leak-recovery",              # both_pass, v3_turns=14
    # Recovered by v3 tool expansion (write_file / python / r)
    "terminal-bench/constraints-scheduling",         # v3_only_pass, v3_turns=8
    "terminal-bench/distribution-search",            # v3_only_pass, v3_turns=11
    "terminal-bench/openssl-selfsigned-cert",        # v3_only_pass, v3_turns=12
    "terminal-bench/count-dataset-tokens",           # v3_only_pass, v3_turns=21
    "terminal-bench/headless-terminal",              # v3_only_pass, v3_turns=25
    # Regression sentinels (passed v1, failed v3)
    "terminal-bench/code-from-image",                # v1_only_pass (now server_bad_request)
    "terminal-bench/pytorch-model-recovery",         # v1_only_pass (unknown_zero in v3)
    "terminal-bench/cancel-async-tasks",             # v1_only_pass (unknown_zero in v3)
    # Prompt-tuning targets (unknown_zero in both v1 and v3)
    "terminal-bench/circuit-fibsqrt",                # early giveup (Mode 1)
    "terminal-bench/dna-assembly",                   # Mode 2 probable
    "terminal-bench/mteb-retrieve",                  # Mode 2 probable
    "terminal-bench/model-extraction-relu-logits",   # Mode 4 probable
    # Hard (turn_exhaustion — capability tail)
    "terminal-bench/build-pov-ray",                  # compiles, never passes in 40 turns
    "terminal-bench/largest-eigenval",               # numeric task, hard
    # Infra edge
    "terminal-bench/chess-best-move",                # AgentTimeoutError in v3; worth tracking
]

# Retained for compatibility.
INNER_EVAL_TASKS = EASY_SUBSET
