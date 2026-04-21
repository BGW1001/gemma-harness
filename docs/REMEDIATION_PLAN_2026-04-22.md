# Remediation Plan — Gemma 4 protocol drift & Qwen3-Coder fallback (2026-04-22)

## Purpose

This document is a working plan for two sequential remediation tracks against the protocol-drift failure mode documented in `docs/OBSERVED_ISSUE_2026-04-21_MODEL_PROTOCOL_DRIFT.md` and `docs/STATUS_2026-04-22.md`.

It supersedes the "defensive sanitizer as primary fix" framing in `docs/DESIGN_2026-04-21_protocol_drift_defense.md`. The sanitizer stays as instrumentation and defense-in-depth, but it is no longer treated as the resolution.

## Correction of an earlier assumption

Previous progress notes referred to the model as "Gemma 3 27B" in some places. This is wrong. The actual model in use is **Gemma 4 26B-A4B** (26B total parameters, 4B active, MoE). This changes the diagnosis materially.

The tokens observed in the crash trace —

```
<|channel>thought … <channel|>
<|tool_call>call:bash{cmd:<|"|>…<|"|>}<tool_call|>
```

— are **not** drift, corruption, or hallucinated GPT-OSS markup. They are Gemma 4's **native, trained, documented control-token vocabulary**. Google publishes them in the [Gemma 4 prompt-formatting doc](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4). The model is doing exactly what it was trained to do. The failure is in the serving path: llama.cpp's `COMMON_CHAT_FORMAT_PEG_GEMMA4` parser currently mis-handles these tokens on round-trip through the `messages` array, producing the HTTP 500 we've been chasing.

This reframes the engineering problem from "the model is behaving badly, defend against it" to "the serving stack has known bugs on a specific code path, and we can either fix the stack or move off it."

## Scope

Two tracks, executed in order:

1. **Track A — Fix the Gemma 4 serving path.** Rebuild llama.cpp with the fixes that are already merged or in flight, refresh the model weights, add grammar-constrained generation, and re-establish baselines. Determine whether Gemma 4 26B-A4B is a viable agent backbone once the serving layer is no longer buggy.
2. **Track B — Qwen3-Coder-30B-A3B-Instruct as a parallel backbone.** Repeat the same harness validation against a model that has a native, mature tool-call parser in llama.cpp and substantially better throughput on this hardware. Determine whether it should be the default Gemma replacement or a second supported option.

Both tracks share the same harness, same EASY_SUBSET, same ledger schema. The point is to get comparable numbers across two backbones so the operator can make an informed call about which one to invest iteration budget in.

## Track A — Fix llama.cpp + Gemma 4

### A.1 Confirm what is actually running

Before any rebuild, the agent should confirm the current build state. The outputs of these commands go into the track's handoff note.

```bash
# Which GGUF, which architecture, which template
llama-gguf <path_to_model>.gguf | head -60

# Which llama.cpp build, which chat format it auto-detected
llama-server --version
# (also check server startup log for "Chat format: peg-gemma4" vs "Chat format: Generic")

# System fingerprint from a live request — format "bNNNN-<hash>"
curl -s http://localhost:8889/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma","messages":[{"role":"user","content":"ping"}],"max_tokens":1}' \
  | jq .system_fingerprint
```

Acceptance: we have a recorded `general.architecture`, `tokenizer.chat_template`, llama.cpp build number, and the chat-format string the server is using. These go in the handoff note as the "before" state.

### A.2 Rebuild llama.cpp at a known-good revision

Target: master at **b8789 or later**, with PR [#21760](https://github.com/ggml-org/llama.cpp/pull/21760) applied if it has not yet merged by the time this work is done.

Relevant ticket state (as of 2026-04-22):

| Ticket | Status | Why it matters |
|---|---|---|
| PR #21326 | merged, ≥ b8653 | Introduces `COMMON_CHAT_FORMAT_PEG_GEMMA4`, `normalize_gemma4_to_json()`, bundled `gemma4.jinja` |
| PR #21343 | merged | Tokenizer fix — the `<unused25>`/`<unused49>` spam and `\n\n` split bug |
| Issue #21316 | open | `<|"|>` leaking into string arg values |
| Issue #21375 | open (repro on b8643) | **PEG parser re-parses every token, server never emits EOS — this is our infinite-reparse → HTTP 500** |
| Issue #21384 | open (b8656) | Array tool-call args serialized as JSON string when values contain `{` or `}` |
| Issue #21912 | open (b8789) | Full prompt reprocessing from system prompt every turn, under OpenCode-style clients |
| PR #21697 | merged | Reasoning-budget sampler wiring |
| PR #21760 | open at time of writing | Handles content+tool-call mix and partial-literal streaming ambiguities |

Build on Strix Halo (gfx1151) with HIP:

```bash
HIPCXX="$(hipconfig -l)/clang" HIP_PATH="$(hipconfig -R)" \
cmake -S . -B build-rocm \
  -DGGML_HIP=ON \
  -DGGML_HIP_ROCWMMA_FATTN=ON \
  -DGGML_HIP_NO_VMM=ON \
  -DAMDGPU_TARGETS=gfx1151 \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_HIP_FLAGS="-mllvm --amdgpu-unroll-threshold-local=600" \
  -DLLAMA_LLGUIDANCE=ON
cmake --build build-rocm -j$(nproc)
```

`-DLLAMA_LLGUIDANCE=ON` is deliberately enabled here so step A.4 has it available. It requires a Rust toolchain.

No-build fallback if the toolchain is painful: [`lemonade-sdk/llamacpp-rocm`](https://github.com/lemonade-sdk/llamacpp-rocm/releases/latest) ships AMD-maintained nightly binaries built on TheRock ROCm-7 for gfx1151. Acceptable to use for Track A validation if the source build stalls.

Acceptance: `llama-server --version` reports a build ≥ b8789; HIP backend loads; a Gemma 4 smoke request returns without 500 on the original MIPS reproducer.

### A.3 Refresh the GGUF

**Unsloth re-uploaded `unsloth/gemma-4-26B-A4B-it-GGUF` on April 11, 2026** with Google's updated chat template and the llama.cpp fixes baked into the template. Any quant downloaded before that date contains the broken template and will keep failing even on fresh llama.cpp.

```bash
# Recommended quant — UD-Q6_K_XL is the sweet spot at this size
huggingface-cli download unsloth/gemma-4-26B-A4B-it-GGUF \
  gemma-4-26B-A4B-it-UD-Q6_K_XL.gguf \
  --local-dir ~/models/gemma-4-26B-A4B-it-GGUF-2026-04-11
```

Do **not** go below Q5 for agentic workloads. Miguel Filipe's quant-reliability study found Gemma 4 relatively quant-robust, but agent harnesses amplify any loss; Q5_K_M is the floor, Q6_K_XL is what we should be running.

A known Unsloth-documented footgun: **do not use the CUDA 13.2 runtime for any Gemma 4 GGUF** — outputs silently degrade. This is irrelevant on ROCm but worth recording so it doesn't bite us if we ever test on a CUDA box.

Acceptance: the new GGUF's `tokenizer.chat_template` contains the April-11 Google template; a diff against the old template is captured in the handoff.

### A.4 Switch from post-hoc sanitization to grammar-constrained generation

The current defensive sanitizer in `harness/harness.py` is a filter applied after the server has already produced output. Under llguidance, the server's sampler is constrained at generation time to a grammar derived from our tool schemas — the model can only emit tokens that continue a valid tool call (or a content-only final). This makes the format-token leakage impossible by construction rather than something we detect and clean up.

Usage pattern against our existing OpenAI-compatible client:

- Pass our tool JSON-Schema on each request via the `grammar` field, or via `-j` at server boot.
- One unresolved interaction to verify: discussion [#12204](https://github.com/ggml-org/llama.cpp/discussions/12204) reports `--jinja` *appearing* to disable request-level `grammar` for some users; the maintainer says it should work. Empirical A/B needed. Capture result in the handoff.
- Keep the sanitizer in place as defense-in-depth. Also keep the drift counter — it now measures how often the grammar path fails open, which is the signal we want.

Acceptance: llama-server starts with llguidance enabled; a canned malformed-output reproducer no longer produces format-token content; `protocol_drift=True` rate on a 20-request smoke test drops to zero.

### A.5 Replace silent sanitize-and-continue with retry-with-repair

Even with a grammar, a well-designed harness should handle tool-validation failures as first-class events. Published evidence (KAMI v0.1, arXiv 2512.07497; "Structured Reflection," arXiv 2509.18847; OpenHands issues #5111 / #10048) is that models self-correct better when handed an explicit error than when the harness silently cleans their output.

Proposed harness change, additive on top of the existing sanitizer:

- On detecting malformed assistant content, inject a synthetic `tool_use_failed` message with a short human-readable reason, rather than stripping the content and continuing as if nothing happened.
- Retry counter bounded by the existing `drift_count` threshold (abort at 2).
- Ledger row gains `repair_attempts` alongside `drift_count`.

This is `harness/*`-locked work, same governance exception as the original Option F patch.

Acceptance: on a task where malformed output is induced, the trace shows a `tool_use_failed` turn, the model's next turn recovers, and the trial completes without aborting.

### A.6 Re-baseline under the fixed stack

Run `bash scripts/baseline.sh` (EASY_SUBSET × 3) with:

- llama.cpp ≥ b8789 + #21760
- Refreshed April-11 Gemma 4 26B-A4B-it GGUF at UD-Q6_K_XL
- `--jinja` + llguidance grammar enabled
- Retry-with-repair wired in
- Sanitizer still on, as instrumentation

Record in `runs/ledger.jsonl` as normal. New `prompt_hash` is expected because the composed template changed; this is the correct outcome.

Acceptance for Track A:

- `make-mips-interpreter` validation completes without a 500.
- `fix-git` pass rate on EASY_SUBSET is at least as high as the pre-remediation 2/3.
- Mean `drift_count` per completed trial is ≤ 0.1.
- At least one of `openssl-selfsigned-cert` or `sanitize-git-repo` produces a non-zero score, **or** the failure mode on those tasks is documented and distinct from protocol drift.

If A.6 passes, Gemma 4 is established as a viable backbone under the fixed stack. Write the results to `memory/learnings.md` and open Track B in parallel rather than in sequence.

If A.6 fails on grounds other than protocol drift (e.g. the model genuinely cannot plan these tasks), document it as a capability ceiling for this model size and move directly to Track B as the primary backbone.

## Track B — Qwen3-Coder-30B-A3B-Instruct as parallel backbone

### B.1 Why this specific model

`common/chat.cpp` has dedicated native tool-call parsers for Llama 3.x, Hermes 2/3/4, Qwen 2.5/2.5-Coder/3/3-Coder, Mistral Nemo, Functionary, GLM-4.5/4.6, GPT-OSS (Harmony), DeepSeek R1, and now Gemma 4 (PEG). Qwen3-Coder gets its own XML-based parser — mature, well-exercised, and structurally simpler than the Gemma 4 PEG grammar.

Concretely for our hardware and goal:

- **Throughput:** 70–86 t/s on Strix Halo versus our current ~40 t/s on Gemma (community benchmarks: kyuz0 toolboxes, lhl/strix-halo-testing, llama.cpp discussion #20856). Roughly doubles the AutoResearch iteration rate.
- **Parser maturity:** Qwen3-Coder XML parser has no analog of the Gemma 4 PEG parser's open issues.
- **Benchmark standing:** BFCL v3 ~80 on live_simple; widely reported strong tool-calling, including explicit endorsement in the OpenHands-on-AMD/Lemonade integration guide as "best speed/quality balance locally."
- **Fit:** At UD-Q6_K_XL the GGUF is ~32 GB. Comfortably fits on 128 GB unified memory with 128k context.

### B.2 Install

```bash
huggingface-cli download unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF \
  Qwen3-Coder-30B-A3B-Instruct-UD-Q6_K_XL.gguf \
  --local-dir ~/models/Qwen3-Coder-30B-A3B-Instruct-GGUF

llama-server \
  -m ~/models/Qwen3-Coder-30B-A3B-Instruct-GGUF/Qwen3-Coder-30B-A3B-Instruct-UD-Q6_K_XL.gguf \
  --jinja \
  --reasoning-format deepseek \
  -ngl 999 -fa on \
  -c 131072 -b 2048 -ub 512 \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --temp 0.7 --top-p 0.8 --top-k 20 --repeat-penalty 1.05 \
  --host 0.0.0.0 --port 8889
```

Same port (8889) as Gemma for a drop-in swap. The harness client hits the same `/v1/chat/completions` endpoint; the `model` field in the request body is ignored by llama-server anyway.

Acceptance: startup log shows the Qwen3-Coder native parser selected (look for `Chat format:` line mentioning qwen3_coder / xml); a single-tool smoke request returns a valid `tool_calls` structure.

### B.3 Harness adjustments

Expected to be minimal. The output contract the model is trained to follow differs slightly (XML-tagged tool calls rather than Gemma 4's channel/tool_call markup), but our harness consumes structured `tool_calls` from the OpenAI-compatible response — llama.cpp's parser converts both models into the same `tool_calls[]` shape for us.

Things to verify:

- `prompts/system.md` — the "Output contract" section was written with Gemma 4 in mind. Qwen3-Coder's own system prompt conventions are slightly different. Compose a Qwen-variant and track it as a separate `prompt_hash`. Do not attempt one unified prompt across both models; per-model prompts are cheaper than hybrid prompts.
- `config.yaml` — `temperature: 0.2` was picked for Gemma. Qwen3-Coder's model card recommends `0.7`. Worth A/B-ing both on EASY_SUBSET and keeping whichever wins.
- `harness/client.py` — no changes expected.
- Sanitizer — can be disabled for Qwen trials, or left on as instrumentation. The drift markup it catches is Gemma-4-specific, so on Qwen it should simply never trigger. If it does, that is itself a signal worth logging.

Acceptance: a Qwen3-Coder-specific `prompt_hash` composes cleanly, and `scripts/validate.sh` (single trial on `fix-git`) completes without infrastructure errors.

### B.4 Baseline Qwen3-Coder on EASY_SUBSET

Same baseline protocol as Track A: `bash scripts/baseline.sh`, EASY_SUBSET × 3, ledger rows appended, `memory/learnings.md` updated.

Acceptance for Track B:

- No protocol-level crashes across 9 trials.
- `fix-git` pass rate ≥ the Gemma 4 fixed-stack result.
- At least one of `openssl-selfsigned-cert` / `sanitize-git-repo` produces a non-zero score.
- `make-mips-interpreter` validation completes without a 500 and produces a scored (not crashed) result, whether reward is zero or not.

### B.5 Head-to-head on EASY_SUBSET

Once both Track A and Track B have a recorded `prompt_hash` that runs cleanly on EASY_SUBSET × 3, compose a single comparison table in `memory/learnings.md`:

| Backbone | prompt_hash | Mean reward | Pass@2 | t/s observed | Drift events |
|---|---|---|---|---|---|
| Gemma 4 26B-A4B (fixed stack) | … | … | … | … | … |
| Qwen3-Coder-30B-A3B-Instruct | … | … | … | … | … |

Decision criteria:

- If Qwen3-Coder wins on both mean reward *and* throughput, it becomes the default harness backbone; Gemma 4 stays as a second supported option under the fixed stack.
- If Gemma 4 wins on reward despite slower throughput, iteration budget goes to Gemma 4; Qwen stays as a fallback.
- If they are within noise on reward, Qwen wins by default because of throughput (faster AutoResearch iterations compound).

## Governance

Both tracks touch locked surfaces (`harness/*`, `eval/*` reruns). This is explicitly unlocked for this work, continuous with the Option F unlock from 2026-04-21. Handoff notes required:

- `~/.openclaw/workspace/handoffs/gemma-harness-track-a-gemma4-fixed-stack-2026-04-??.md`
- `~/.openclaw/workspace/handoffs/gemma-harness-track-b-qwen3-coder-2026-04-??.md`

Each handoff captures before-state, actions taken, after-state, and a single-paragraph summary for `memory/learnings.md` promotion.

## Things explicitly out of scope

- Switching backend away from llama.cpp (vLLM / SGLang / TGI on gfx1151 are not production-ready as of April 2026; defer).
- Switching to a non-MoE small model (Mistral Small, Phi-4). Defer unless both Gemma 4 fixed and Qwen3-Coder fail on capability grounds rather than infrastructure grounds.
- Fine-tuning either model. Out of project scope as defined in the original handoff brief.
- Rewriting the AutoResearch outer loop. Defer until one backbone produces consistent non-zero scores on EASY_SUBSET.

## References

Primary:

- llama.cpp Gemma 4 function-calling path: [`common/chat.cpp`](https://github.com/ggml-org/llama.cpp/blob/master/common/chat.cpp), [`docs/function-calling.md`](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
- Gemma 4 prompt formatting (official): https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4
- Unsloth Gemma 4 run guide: https://unsloth.ai/docs/models/gemma-4
- llguidance: https://github.com/guidance-ai/llguidance

Tracker (Gemma 4 specific):

- PR #21326 (parser), #21343 (tokenizer), #21697 (reasoning budget), #21760 (content+tool mix) — https://github.com/ggml-org/llama.cpp/pulls
- Issues #21316, #21375, #21384, #21516, #21912 — https://github.com/ggml-org/llama.cpp/issues

Strix Halo / gfx1151:

- AMD Lemonade SDK llama.cpp builds: https://github.com/lemonade-sdk/llamacpp-rocm
- kyuz0 Strix Halo toolboxes: https://github.com/kyuz0/amd-strix-halo-toolboxes
- lhl strix-halo-testing: https://github.com/lhl/strix-halo-testing

Harness patterns:

- KAMI v0.1 (mid-trajectory tool-call malformation): https://arxiv.org/abs/2512.07497
- Structured Reflection: https://arxiv.org/abs/2509.18847
- OpenHands tool-error patterns: https://github.com/All-Hands-AI/OpenHands/issues/5111

Internal:

- `docs/OBSERVED_ISSUE_2026-04-21_MODEL_PROTOCOL_DRIFT.md` — the original failure writeup
- `docs/DESIGN_2026-04-21_protocol_drift_defense.md` — sanitizer design, now demoted to defense-in-depth
- `docs/STATUS_2026-04-22.md` — state at start of this plan
- `docs/OVERVIEW.md` — canonical project overview
