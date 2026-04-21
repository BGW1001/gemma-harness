# Skill: plan

**When to apply:** at the start of every task, and whenever the current plan is invalidated by new information.

## Protocol

1. **Extract the grader contract.** Read the user instruction and list:
   - Exact file paths the grader will check
   - Exact content/format those files must contain
   - Any forbidden commands or constraints
   If any of these are ambiguous, write your best interpretation as an assumption and continue.

2. **Decompose into 3–6 concrete steps.** Each step must:
   - Name a specific file, command, or check
   - Have an observable outcome (a file exists, a command exits 0, output contains X)
   - Be cheap enough to execute in 1–3 turns

3. **Order by dependency and value.** Do the step that unlocks the most later work first. If two steps are independent, do the one that writes the required artifact first.

4. **Write the plan once near the start of the run.** Re-state it only when it changed, when you are stuck, or when doing so materially helps you reason.

## Revision triggers

Revise the plan (and say why in one sentence) when:
- A tool call returned an error that invalidates a later step
- A probe revealed the task is smaller/larger than assumed
- You have repeated a step twice and made no progress — cut it or replace it

## Anti-patterns

- Plans that start with "understand X" or "explore X" without an observable outcome
- Plans longer than 6 steps — decompose later
- Plans that don't name the files the grader checks
- Repeating the full plan mechanically every turn
