# Policy: stop-loops

**Rule:** never emit a tool call with identical arguments to the immediately preceding tool call.

## Why

A repeated identical call cannot return new information. Repeating it wastes a turn and indicates the agent is stuck. The MIPS trial failure log showed three consecutive identical `grep -a syscall6 doomgeneric_mips | head -n 100` calls returning the same 130KB of binary data.

## How to apply

Before every tool call, check: "Did my last tool call have the same name and the same arguments?"

- If **yes** → do not emit this call. Instead:
  1. State in `content`: "Previous call returned X; repeating would not help. Trying: ..."
  2. Change at least one of: the tool, the command, the file, the flags, or the search pattern.
  3. If no variant seems likely to help, move to the next plan step and mark the current one as "blocked — skipped."

- If the last two calls already differed but both produced errors/same-shape-output, widen the change: switch tool, or reduce scope (a file instead of a directory, a head instead of full dump).

## Special case: reading large / binary outputs

If a single tool call returned more than 10KB, do not re-issue it. Parse what you already have.
