# Workshop — fine-tuning and distillation options for Qwen3.6-35B-A3B (2026-04-24)

**Status:** exploratory. Not a decision. Original project scope explicitly excluded fine-tuning; this doc is a workshop of what those routes would look like if the scaffold-and-prompt ceiling turns out to be meaningfully below the target. Use to think, not to commit.

**Current state as of writing:** v3 @ 27/89 Pass@1 (30.3) → plausibly 35-40 with further scaffold+prompt work. Below the claimed 51.5 for Qwen3.6-35B-A3B. Fine-tuning or distillation only warrant serious consideration if scaffold iteration plateaus below the target.

---

## Part 1 — Fine-tuning Qwen3.6-35B-A3B directly

Goal: improve Qwen3.6 on Terminal-Bench 2 (or agent-use more broadly) by training further on agent trajectories.

### Step 1 — Data collection

Training needs example trajectories. Sources, in increasing cost and quality:

| Source | Cost | Quality | Notes |
|---|---|---|---|
| v3 successful trajectories | free | medium | 27 tasks × 1 attempt. Too few. |
| v3 + v4 + future MINI_SET runs | free | medium | Accumulates over time. Still probably <500 trajectories. |
| Teacher-generated trajectories | $$ | high | See Part 2 (distillation). |
| Public SWE-bench / task-bench-live trajectories | free | variable | Aider, OpenHands, SWE-agent publish trajectory data. Different task distribution. |
| Synthetic task generation | $$ | variable | Have a model generate tasks similar to TB2, then solve them. |

Minimum viable dataset for agent fine-tuning: ~1000-5000 trajectories. We have far less than that from v3/v4 alone. This is the biggest single blocker.

### Step 2 — Data format

Convert ReAct trajectories to fine-tuning format:

- OpenAI/Qwen messages format: `[{role: system|user|assistant|tool, content: str, tool_calls: [...]}]`
- For Qwen3.6 with thinking mode: preserve `reasoning_content` vs `content` separation in assistant turns
- **Mask loss on tool results** — don't train the model to predict tool output (which it can't; tools are external).
- Include a `role: system` with the same prompt the eval-time agent uses. Consistency matters.
- Per-trajectory quality filter: keep only `reward == 1.0`, optionally keep `reward == 0.0` but mark as "bad example" for later DPO use.

### Step 3 — Training infrastructure

Qwen3.6-35B-A3B is 35B total / 3B active MoE. Three routes by cost:

| Route | Memory needed | Hardware fit | Ease |
|---|---|---|---|
| **Full fine-tune** | ~70 GB × 4 replicas | 4× A100-80G or equivalent cluster | Hard |
| **LoRA on BF16 base** | ~35 GB + LoRA overhead | Single H100 (80GB), tight on A100-80G | Medium |
| **QLoRA (4-bit base + LoRA)** | ~18 GB + LoRA overhead | Single 48GB GPU, or Strix Halo unified memory (128 GB) | **Easiest** |

For Strix Halo (our hardware): QLoRA is the only realistic path. The 128 GB unified memory covers the 4-bit base, KV cache, LoRA adapters, and optimizer state with room to spare — but ROCm training-stack maturity is the open question. Would need to test:

- `unsloth` has Qwen3 support on CUDA; HIP/ROCm support is less mature
- `axolotl` is flexible but ROCm support varies by backend
- `transformers` + `peft` + `bitsandbytes` — bitsandbytes 4-bit is CUDA-only historically; ROCm fork exists but less exercised

**Realistic conclusion**: first-time fine-tune probably needs a cloud H100 for a few days. ~$20-50/hour × ~72 hours ≈ $1500-3500 for one training run + iteration budget.

### Step 4 — Training recipe (LoRA SFT)

Standard template:

```yaml
adapter: lora
lora_r: 32
lora_alpha: 64
lora_target_modules: [q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj]
learning_rate: 1e-4
batch_size: 1
gradient_accumulation_steps: 16
num_epochs: 2-3
warmup_ratio: 0.03
weight_decay: 0.0
lr_scheduler_type: cosine
bf16: true
gradient_checkpointing: true
```

Key decisions:
- **Training on thinking-mode outputs:** preserve `reasoning_content` in the training data, or strip it? Qwen3.6's thinking-mode is load-bearing for agent quality. Train on both.
- **Loss on tool_calls vs content:** train on `tool_calls` shape (model learns to emit well-formed JSON). Mask on `tool` role (tool-result messages).
- **Sequence packing:** long agent trajectories are the training signal; don't truncate them aggressively. Aim for 16k-32k token context window during training.

### Step 5 — Evaluation during training

- Checkpoint every ~500 steps (or once per epoch, whichever is more frequent)
- Run MINI_SET at each checkpoint (2-3h)
- Keep the best-on-MINI_SET checkpoint, discard the rest
- Final evaluation: full TB2 benchmark on the winner

### Step 6 — Serving the fine-tuned model

Merge LoRA into base weights:

```python
from peft import PeftModel
base = AutoModel.from_pretrained("Qwen/Qwen3.6-35B-A3B", torch_dtype="bf16")
tuned = PeftModel.from_pretrained(base, "path/to/lora-adapter").merge_and_unload()
tuned.save_pretrained("path/to/merged-weights")
```

Then re-quantize to GGUF for llama.cpp:

```bash
python llama.cpp/convert_hf_to_gguf.py path/to/merged-weights \
  --outfile path/to/merged-q6kxl.gguf --outtype q6_k
```

Swap the systemd unit to point at the new GGUF. Rollback = point back at Unsloth stock GGUF.

### Step 7 — Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Overfit to TB2 shape** | Include diverse non-TB data (~20-30% of training mix). SWE-bench, HumanEvalAgent, tool-use conversations. |
| **Thinking-mode degradation** | Train on thinking-mode data; evaluate with thinking-mode on. Explicitly preserve `reasoning_content` field. |
| **Quantization loss post-merge** | Evaluate merged BF16 first; quantize only after confirming no quality drop. Q6_K_XL was chosen at baseline for a reason. |
| **Catastrophic forgetting** | Limit epochs to 2-3; LoRA rather than full fine-tune limits damage; include general instruction data in mix. |
| **Regression on easy-subset tasks** | Track EASY_SUBSET + MINI_SET every checkpoint; reject any checkpoint that regresses on both_pass bin. |

### Effort estimate

- Infrastructure setup (ROCm training OR cloud H100 rental): **3-5 days**
- Data pipeline (collect trajectories, format, filter): **2-3 days**
- First training run + eval: **2-3 days**
- Iteration on hyperparams + data mix: **1-2 weeks**
- **Total: 3-5 weeks realistic**

### Expected payoff

Honestly hard to predict. For agent tasks on a model this size, the lift from SFT alone is typically **+3-8 percentage points** on a benchmark like TB2 — so 30.3 → maybe 33-38. Not a qualitative jump. DPO on top might add 2-5 more points.

If we hit a real scaffold+prompt ceiling and need another 10 points, this is a reasonable path. If scaffold is still moving the number, this is expensive relative to alternatives.

---

## Part 2 — Distillation from a larger teacher model

Goal: use a SOTA model (Claude Opus, GPT-5, Gemini, Qwen3-MAX) to generate high-quality agent trajectories, then train Qwen3.6 to imitate.

### Step 1 — Pick the teacher

Considerations:

| Teacher | Strength | Agentic fit | API cost |
|---|---|---|---|
| Claude Opus 4.7 | General reasoning, verbose structured outputs | Excellent (Claude Code itself) | High |
| GPT-5 | Strong agentic, wide tool-use knowledge | Excellent | Medium-high |
| Qwen3-MAX | Family-consistent tokenizer + template | Good, stays in-family | Lower |
| Gemini 2.5 Pro | Different training distribution | Good | Medium |
| Open-weight 70B+ (e.g. Llama 4 70B) | Free inference | Weaker agent performance | Free (hardware) |

**Family-consistency matters for distillation.** If the teacher uses the same tokenizer and chat template, the student's embedding space aligns naturally with the training signal. Qwen3-MAX as teacher → Qwen3.6 as student is the cleanest pairing, if Qwen3-MAX's agentic performance is strong enough.

If we use a non-Qwen teacher: we'd need to re-tokenize trajectories through Qwen3.6's tokenizer, which is fine but adds a preprocessing layer.

### Step 2 — Teacher trajectory generation

Run Terminal-Bench 2 (and other agent benchmarks) with the teacher as the agent via our Harbor stack. Each task produces a full conversation trace.

Cost at Claude Opus rates as of writing:
- ~$15/M input tokens, ~$75/M output tokens
- Average TB2 trajectory: ~20k input + 10k output tokens per turn × 15 turns = ~300k input + 150k output per trajectory
- Per-trajectory cost: ~$4.5-15
- 89 tasks × 3 attempts = 267 trajectories × $10 median = **~$2,670**

Plus broader agent data (SWE-bench, custom tasks): another ~$5-10k for a comprehensive dataset.

**Total teacher data generation cost: $5-15k** for a good corpus. Not trivial but less than a full-GPU training run's cloud time.

### Step 3 — Filter and normalize

- Keep only `reward == 1.0` trajectories
- Strip teacher-specific artifacts (different tool names, different system prompt wording)
- **Map teacher's tool calls to student's available tools**: Claude's `Read` → student's `file_view`, etc.
- Re-tokenize with student's tokenizer
- Validate: each training example must be parseable by student's chat template

This step is trickier than it sounds. Teachers may use tools students don't have. Two options:
- **Expand student's tool surface to match teacher's** (extends `tools.py`)
- **Filter out trajectories that use unavailable tools**

### Step 4 — SFT training

Same LoRA pipeline as Part 1, with teacher trajectories as the dataset. Key differences:

- Dataset is cleaner (teacher solved, student learns from success only)
- Dataset may be larger (can generate thousands easily)
- Include a "distillation tax" regularization: cross-entropy between student and teacher's next-token distribution if both available, or simple SFT if only teacher outputs captured

### Step 5 — On-policy refinement (DPO / RLAIF)

Optional but usually helpful. After SFT:

1. Student attempts each task, producing its own (possibly still failing) trajectories
2. Teacher rates pairs of student attempts: which is better?
3. DPO loss on the preference pairs — student learns to prefer teacher-approved behavior

Cost: another ~$2-5k in teacher API calls for preference generation.

Expected additional lift: +2-5 percentage points over SFT alone.

### Step 6 — Evaluate + serve

Same MINI_SET → full benchmark pipeline. Same merge + quantize + swap systemd unit pattern.

### Step 7 — Distillation-specific risks

| Risk | Mitigation |
|---|---|
| **Student mimics teacher's style without reasoning** | Evaluate on held-out tasks the teacher didn't solve — if student scores there, it's real generalization |
| **Teacher trained on TB2 / SWE-bench data** | Assume contamination; supplement with novel tasks from held-out set |
| **Length bias** (students over-verbose) | Track turn counts post-training; penalize high-turn trajectories in evaluation |
| **Distribution mismatch on tools** | Make the tool surface match before training; don't train on trajectories using unavailable tools |
| **Mode collapse** (student only learns one solving style) | Include diverse teachers or temperature variation in teacher rollouts |

### Effort estimate

- Teacher selection + API access setup: **1-2 days**
- Data generation run: **2-4 days wall** (running teacher through 267+ tasks takes time; $5-15k total)
- Data cleaning and tool-mapping: **3-5 days**
- SFT training (LoRA): **2-3 days**
- DPO refinement: **3-5 days**
- Evaluation + iteration: **1-2 weeks**
- **Total: 5-8 weeks realistic, $5-20k teacher API + hardware costs**

### Expected payoff

For a well-executed distillation of a SOTA teacher into a 35B MoE student:

- SFT-only from a strong teacher: **+5-10 percentage points** typically
- SFT + DPO: **+8-15 points** typically
- Bounded by student capacity (3B active params is a real ceiling)

So 30.3 → plausibly 40-45 with distillation. **Gets us in range of the claimed 51.5 for the first time.**

---

## Part 3 — Combined strategy (most ambitious)

For best results, combine:

1. Teacher-generated SFT data (good supervision) + our v3/v4 successful trajectories (domain-specific)
2. Train LoRA with mixed dataset
3. DPO with teacher as preference judge on student's attempts
4. Continue harness improvements in parallel

This is a 2-3 month project at least one engineer full-time.

---

## Part 4 — Honest decision framework

Fine-tuning or distillation is a BIG commitment. Before going down that road, exhaust cheaper levers:

**Cheaper alternatives with plausible similar-scale lift:**

| Alternative | Estimated effort | Estimated lift |
|---|---|---|
| Build all Tier-1 tools from `TOOLS_WORKSHOP_2026-04-23.md` (`read_file_range`, `apt_install`, `apply_patch`, `done`) + guidance prompt | 1-2 days | **+3-5 points** |
| Build Tier-2 + workshop repo_map + persistent_bash | 1 week | **+3-6 points** |
| Several AutoResearch prompt iterations on MINI_SET | 2-3 weeks | **+4-8 points** |
| Try larger Qwen model (Qwen3.6-72B when available, or current Qwen3-MAX) as the backbone | 2-3 days | **+5-15 points** (if hardware supports it) |
| Pass@2 / Pass@3 evaluation (multiple attempts scored as any-pass) | 1 day | automatic +5-8 points on reported score |

**Compared to:**

| Approach | Effort | Estimated lift | Cost |
|---|---|---|---|
| Fine-tune Qwen3.6 (LoRA SFT) | 3-5 weeks | +3-8 points | $1.5-5k |
| Distill from a strong teacher | 5-8 weeks | +8-15 points | $10-25k |

**My current read:** scaffold + prompt work isn't exhausted yet. We just got 58% relative from scaffold alone. Two more rounds of Tier-1 tools + a couple of decent prompt iterations on MINI_SET is probably worth ~5-8 more points, taking us to ~35-38. That's meaningfully closer to 51.5 without the fine-tuning-scale commitment.

**Where fine-tuning becomes the right call:**

1. We've iterated scaffold for 2+ months and are genuinely plateauing
2. A specific failure class (e.g. capability-ceiling Mode 3 tasks) is the dominant blocker and no scaffold change will help
3. Organizational / cost factors make "one good fine-tune" cheaper than "many small scaffold iterations"
4. We want to publish a tuned-open-model result competitive with larger closed models (the OSS narrative the earlier workshop mentioned)

**Where distillation becomes the right call:**

1. We have budget for $10-25k in teacher API calls
2. We want a quality jump beyond what SFT-on-our-own-data can give
3. We're willing to accept the risk of overfitting to the teacher's style

---

## What we'd ship if we committed (rough sequencing)

Parked as next-phase-if-we-commit plan:

1. **Harden MINI_SET as our eval substrate** — prove it ranks accurately (~2-3 weeks of iteration)
2. **Cheap gains first** — Tier-1 tools + 2-3 prompt variants (~2-3 weeks)
3. **Upgrade backbone** if available — try Qwen3.7 or Qwen-MAX as drop-in replacements (~1 week)
4. **Then consider** distillation from a SOTA teacher if still plateaued below ~45

Only go to fine-tuning or distillation when scaffold has demonstrably stopped moving. Don't start the 2-3 month thing while cheaper wins remain.

---

## References

- `docs/DESIGN_2026-04-24_mini_set.md` — the eval substrate this plan assumes
- `docs/ANALYSIS_2026-04-24_unknown_zero.md` — what kinds of failures fine-tuning would target
- `docs/TOOLS_WORKSHOP_2026-04-23.md` — the cheaper alternatives inventory
- Qwen3.6 model card: https://huggingface.co/Qwen/Qwen3.6-35B-A3B
- Unsloth fine-tuning guide: https://unsloth.ai/docs
- DPO paper: https://arxiv.org/abs/2305.18290
- LoRA paper: https://arxiv.org/abs/2106.09685
- SWE-RL (execution-free reward for RL): https://arxiv.org/abs/2502.18449
