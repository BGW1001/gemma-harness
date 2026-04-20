# Review Note — `docs/OVERVIEW.md` (2026-04-21)

## Verdict
`docs/OVERVIEW.md` is a strong working overview of the project. It is coherent, strategically aligned, and substantially better than relying on scattered progress notes.

The main issue is **not** bad reasoning. The main issue is that the document occasionally sounds **more empirically settled than the project actually is**.

In other words:
- the architecture story is good
- the process story is good
- the aspiration is good
- but the boundary between **validated** and **intended** should be made sharper

---

## What the doc does well

### 1. Strong project framing
The doc correctly defines the core mission:
- improve the harness around Gemma
- do not fine-tune the model
- do not cheat by swapping in a larger model

That is the right framing and should stay.

### 2. Clear Harbor architecture explanation
The Harbor → task container → `GemmaAgent` → llama.cpp flow is explained clearly and correctly.

This is particularly valuable because earlier integration confusion came from treating Harbor like a utility library rather than an orchestrator.

### 3. Excellent editable-vs-locked split
This is one of the strongest sections.

The distinction between:
- editable artifact surface
- locked plumbing

is exactly the right abstraction if the project is going to evolve into a real AutoResearch loop.

### 4. Good framing of the progress milestone
The doc correctly captures the most important project-level fact:

> We are no longer debugging pure infrastructure. We are now able to produce meaningful benchmark failures.

That is the right milestone to emphasize.

### 5. The suggested next-step ordering is sensible
The current ordering is strong:
1. run baseline under the updated harness/prompt surface
2. inspect trajectories
3. improve agent behavior
4. only then wire optimizer automation

That ordering matches the actual maturity of the project.

---

## Main review concern
The document sometimes presents future-facing design as if it were already fully implemented and validated.

That is dangerous for workshop discussion because it can create false confidence about where the system actually is.

A good rule for the next revision:

- **Implemented + validated** → state plainly
- **Implemented but not yet validated** → label clearly
- **Designed / intended / next-step architecture** → label clearly

Right now those three categories blur in a few places.

---

## Specific suggestions

## 1. Tighten the success semantics in the agent-loop section
### Current issue
The loop description includes wording equivalent to:
- if `finish_reason == "stop"`, return success

That is too risky semantically.

### Why it matters
We already know from the broader work that model termination is **not** success.
Only the Harbor verifier determines whether the task actually succeeded.

### Recommended revision
Rewrite that part so it clearly distinguishes:
- **agent loop termination**
- **task success as judged by the verifier**

Suggested wording:

> If the model returns `finish_reason == "stop"`, the inner loop ends and returns control to Harbor. This is not task success by itself; task success is determined only by the task verifier reward.

That one clarification will prevent a lot of future confusion.

---

## 2. Strengthen the “current state” section with a more explicit empirical status line
### Current issue
The document is accurate overall, but it could be read too optimistically by someone skimming.

### Recommended addition
Add a blunt current-state sentence such as:

> As of 2026-04-20, the harness is infrastructure-ready but not yet benchmark-competitive. The first meaningful post-fix validation run completed successfully but still scored 0.0 on `make-mips-interpreter`.

Why this helps:
- it preserves honesty
- it prevents the workshop from drifting into “we’re basically done with setup”
- it keeps attention on the real next phase: agent performance

---

## 3. Distinguish more clearly between “artifact surface exists” and “artifact surface is validated”
### Current issue
The overview describes the prompt/skill/policy surface very confidently.
That is good structurally, but it currently reads closer to “this has already been shown to work” than “this is the intended controlled search surface.”

### Recommended revision
For sections on:
- `prompts/system.md`
- `skills/*.md`
- `policies/*.md`
- `config.yaml`
- `prompt_hash` attribution

consider adding a short qualifier like:

> This surface is now implemented as the intended search/control layer. Its effectiveness is not yet fully validated; the next baseline run is meant to test whether it produces the first non-zero signal.

That keeps the doc honest without weakening the design.

---

## 4. Tone down certainty around `EASY_SUBSET` unless it has already been empirically validated
### Current issue
The `EASY_SUBSET` section is plausible and thoughtful, but it reads like settled calibration fact.

### Risk
If those tasks have not yet been shown empirically to be the right “get off zero” subset for Gemma, the doc is overstating confidence.

### Recommended revision
Change the tone from:
- “these are the right tasks”

to something like:

> `EASY_SUBSET` is the current proposed calibration subset: tasks chosen because they appear procedurally tractable and within Gemma’s plausible ceiling. This remains a hypothesis until baseline runs show that the subset is capable of producing useful score variation.

That’s a better fit to the current evidence.

---

## 5. Consider moving some of the heavier openclaw-agent-process material into its own doc
### Current issue
The `openclaw agent layer` section is thoughtful, but it is comparatively heavy relative to the rest of the overview.

### Concern
For someone opening `OVERVIEW.md`, the main thing they need is:
- what the system is
- what has been proven
- what is next

The deeper memory/process machinery is valuable, but it may be better as a dedicated companion doc.

### Suggested approach
Keep a short summary in `OVERVIEW.md`, then move the fuller detail into something like:
- `docs/OPERATING_MODEL.md`
- or `docs/AGENT_PROCESS.md`

This is not urgent, but it would likely improve readability.

---

## 6. Add a short “validated today vs pending next” summary table
This would improve the overview a lot.

Suggested structure:

| Item | Status |
|---|---|
| Harbor install | Validated |
| Terminal-Bench 2 dataset path | Validated |
| Harbor task execution | Validated |
| Harbor tool execution | Validated |
| Multi-turn agent loop stability | Validated |
| Non-zero benchmark score | Not yet achieved |
| EASY_SUBSET usefulness | Pending validation |
| AutoResearch optimizer loop | Not yet wired |

This kind of table would make the document immediately more workshop-friendly.

---

## Suggested one-paragraph replacement for the key current-state framing
If helpful, here is a concise framing paragraph that could be dropped into `OVERVIEW.md` with minimal editing:

> As of 2026-04-20, the project has completed the Harbor enablement phase. Harbor, Docker, the Terminal-Bench 2 dataset path, and the custom `GemmaAgent` execution path have all been validated end-to-end. Tool execution and multi-turn loop stability issues have been fixed. The first meaningful post-fix benchmark run completed successfully but still scored 0.0 on `make-mips-interpreter`, which means the project’s current bottleneck is now agent performance rather than infrastructure.

---

## Overall assessment
### Score
**8/10 as a main project overview**

### Why
Because it is:
- coherent
- strategically aligned
- well-structured
- useful for planning

### Why not higher
Because it occasionally compresses the distinction between:
- built
- validated
- intended

That is the one thing I would fix before treating it as the canonical workshop briefing doc.

---

## Bottom line
Keep `docs/OVERVIEW.md` as the main overview.

But in the next revision, tighten the document around one core principle:

> Separate validated reality from designed intent.

If that is done, the overview will be strong enough to act as the canonical reference for co-work and next-step planning.
