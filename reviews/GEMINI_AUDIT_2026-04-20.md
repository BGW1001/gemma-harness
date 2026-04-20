# Gemini Audit — Gemma Harness

**Reviewer:** Gemini 3.1 Pro (via BClaw sub-agent)
**Date:** 2026-04-20
**Scope:** Repo audit against the current checklist, plus a tighter execution plan to first baseline run
**Constraint:** Audit + planning only, no code changes

---

## A. Current state summary

The repository contains the basic scaffolding for the project. The core agent loop (`harness/harness.py`), OpenAI client wrapper (`harness/client.py`), and tool schemas/implementations (`harness/tools.py`) are drafted. `prompts.py` and `config.yaml` exist.

However, **all evaluation, scoring, optimization logic, and test/baseline scripts are fully stubbed** with `NotImplementedError` or empty structures. The harness has not yet been proven to work end-to-end on a real task.

---

## B. Exact gaps by file/function

- **Step 3 / Trivial proof:** Missing an entrypoint (e.g. `scripts/test_trivial.py`) to instantiate `harness.run()` and prove it works end-to-end.
- **`eval/subsets.py`**: `INNER_EVAL_TASKS = []` is empty. The 10 Terminal-Bench tasks are undefined.
- **`eval/terminal_bench.py`**: `run_terminal_bench_subset(config)` is stubbed (`raise NotImplementedError`).
- **`eval/scoring.py`**: `pass_rate(results)` is stubbed.
- **`optimizer/archive.py`**: `write_run_ledger(entry, runs_dir)` is stubbed.
- **`optimizer/propose.py`**: `propose_change(history)` is stubbed.
- **`optimizer/apply.py`**: `apply_candidate(candidate)` is stubbed. It also needs exact logic to enforce the Phase 1 constraint: optimizer may modify `prompts.py` and `config.yaml` only; `harness/*` stays locked.
- **`optimizer/loop.py`**: `main()` is stubbed.
- **`scripts/baseline.sh`**: Stubbed (`echo "baseline not implemented yet"`).
- **`scripts/overnight.sh`**: Stubbed.

---

## C. Critical path to first baseline run

To reach the objective of running the baseline 3x before starting AutoResearch, execute this sequence:

1. **Prove the harness**
   - Create a simple test script to run a trivial task (e.g. “create a file with the word `hello`”) using `harness.run()`.
   - Verify the loop exits cleanly.

2. **Define eval tasks**
   - Populate `eval/subsets.py:INNER_EVAL_TASKS` with the 10 specific inner-subset Terminal-Bench tasks and their success criteria.

3. **Build the eval runner**
   - Implement `eval/terminal_bench.py:run_terminal_bench_subset`.
   - It should map over the tasks, create isolated temporary working directories (CWDs) for each task, call `harness.run()`, and collect traces.

4. **Implement scoring and archive**
   - Implement `eval/scoring.py:pass_rate` to evaluate task traces against success criteria.
   - Implement `optimizer/archive.py:write_run_ledger` to save results to `runs/`.

5. **Wire the baseline script**
   - Update `scripts/baseline.sh` to trigger `run_terminal_bench_subset`, calculate `pass_rate`, and write the run ledger.

6. **Execute baseline 3x**
   - Run the baseline script three times to measure baseline variance.

**Important:** `optimizer/propose.py` and `optimizer/apply.py` are purposely excluded from this critical path. They are part of AutoResearch and should only be implemented **after** the baseline is stable.

---

## D. Recommended next slice

**Focus exclusively on Step 3: the trivial proof.**

Before touching Terminal-Bench or `eval/`, write a throwaway script that feeds a basic prompt into:

- `task = "write 'success' to test.txt"`
- `cwd = "/tmp/test_dir"`
- `config = {max_turns: 40, temperature: 0.2, max_tokens_per_call: 2048}`

Then verify:
- the `chat` loop runs,
- `_bash`, `_file_view`, `_file_edit`, and `_grep` can be called successfully,
- there are no parsing errors,
- the loop reaches a clean stop,
- and the artifact (`test.txt`) actually exists.

---

## E. Risks / gotchas

1. **CWD containment in eval**
   - `tools.py` has `_safe_path`, but `run_terminal_bench_subset` must ensure every task runs in a fresh isolated temporary CWD to prevent cross-task contamination.

2. **Eval scoring rigor**
   - Do not treat `finish_reason == "stop"` as success. The model can hallucinate success.
   - `pass_rate` must evaluate verifiable file states or command outputs.

3. **Tool looping**
   - `harness.py` respects `max_turns`, but currently lacks a guardrail against repeatedly calling the exact same failing tool many times in a row.

4. **Terminal-Bench output parsing complexity**
   - The exact integration contract with Harbor / Terminus 2 needs to be made explicit before `eval/terminal_bench.py` is implemented.

5. **Phase 1 optimizer boundary**
   - `optimizer/apply.py` must strictly reject edits to anything outside `prompts.py` and `config.yaml`.

---

## Bottom line

The project is still in the **scaffold-plus-tools** stage.

The correct next move is **not** to build the optimizer yet.
The correct next move is to **prove the harness can solve one trivial task end-to-end**, then build the benchmark/eval layer, then baseline 3x, and only after that begin the AutoResearch loop.
