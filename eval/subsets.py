# Terminal-Bench 2 task subsets for the inner evaluation loop.
#
# EASY_SUBSET: the "get off zero" target. Three tasks at the procedural /
# well-scoped end of the benchmark, chosen after inspecting task
# instructions and reference solutions. If Gemma cannot reliably solve
# at least one of these, prompt/policy tuning is noise.
#
# Selection criteria:
#   - Reference solution is <100 lines of shell/python
#   - Success criteria are concrete file-existence / content checks
#   - No compiler / interpreter / kernel authoring required

EASY_SUBSET = [
    "terminal-bench/fix-git",                  # 7-line solution: reflog + checkout + merge
    "terminal-bench/openssl-selfsigned-cert",  # ~98-line procedural recipe: openssl commands
    "terminal-bench/sanitize-git-repo",        # moderate but well-scoped: find secret, clean repo
]

# Retained for compatibility.
INNER_EVAL_TASKS = EASY_SUBSET
