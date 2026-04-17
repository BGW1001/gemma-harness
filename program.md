# Harness Optimization

## Objective
Maximize pass rate on Terminal-Bench 2 inner eval (10 tasks).
Metric: pass_rate ∈ [0.0, 1.0], higher is better.

## Editable (Phase 1)
- prompts.py
- config.yaml

## Locked
- harness/*

## Constraints
- max_turns ∈ [10, 200]
- temperature ∈ [0.0, 1.5]
- prompts must be non-empty strings
- config must parse as valid YAML

## Search hints
Known-helpful patterns: explicit planning, post-tool reflection,
concrete tool descriptions, best-of-N on hard turns, context pruning
between turns.

## Stopping
- 100 experiments, OR
- no improvement for 20 consecutive experiments
