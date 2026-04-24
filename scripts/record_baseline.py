"""
Parse a completed Harbor job directory and append one row per trial to
runs/ledger.jsonl.

Ledger row schema:
  timestamp        — ISO-8601 UTC when recording happened
  job_name         — harbor job directory name
  task_name        — e.g. "terminal-bench/fix-git"
  trial_name       — unique trial id from harbor
  reward           — float score from verifier (0..1)
  turns            — turns the gemma agent used
  max_turns        — turn budget from config.yaml
  prompt_hash      — sha256(system prompt) — identifies the editable-surface version
  config           — the {temperature, max_tokens_per_call, ...} config.yaml
  failure_tag      — heuristic: "success" | "partial" | "malformed_model_output"
                     | "model_timeout" | "turn_exhaustion" | "graceful_giveup"
                     | "tool_error_cascade" | "unknown_zero"
  runtime_sec      — wall time
  drift_count      — number of turns in which protocol-drift markup was sanitized
  repair_attempts  — number of synthetic repair injections made (Track A / A.5)

Usage:
  python scripts/record_baseline.py jobs/<job_name>
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def prompt_hash() -> str:
    from prompts import SYSTEM_PROMPT
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:16]


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def tag_failure(reward: float, turns: int, max_turns: int, trace: list, status: str) -> str:
    if reward >= 1.0:
        return "success"
    if reward > 0.0:
        return "partial"
    # reward == 0 — status from the inner loop takes precedence over heuristics
    if status.startswith("harbor_exception:"):
        return status  # preserve the specific exception type
    if status == "malformed_model_output":
        return "malformed_model_output"
    if status == "model_timeout":
        return "model_timeout"
    if status == "output_truncated":
        return "output_truncated"
    if status == "server_tool_parse_error":
        return "server_tool_parse_error"
    if status == "server_bad_request":
        return "server_bad_request"
    if status == "done_explicit":
        return "done_no_pass"  # model called done() but reward=0
    if turns >= max_turns - 1:
        return "turn_exhaustion"
    # Heuristic for graceful giveup: last assistant message has long content + no tool call.
    for msg in reversed(trace or []):
        if msg.get("role") == "assistant":
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls and len(content) > 200:
                low = content.lower()
                if any(k in low for k in ("can't", "cannot", "too hard", "beyond", "unable", "massive undertaking", "not able to")):
                    return "graceful_giveup"
            break
    # Heuristic for tool-error cascade: >50% of tool results had nonzero returncode
    tool_msgs = [m for m in (trace or []) if m.get("role") == "tool"]
    err_count = 0
    for m in tool_msgs:
        try:
            body = json.loads(m.get("content", "{}"))
            rc = body.get("returncode")
            if rc not in (0, None):
                err_count += 1
        except Exception:
            pass
    if tool_msgs and err_count / len(tool_msgs) > 0.5:
        return "tool_error_cascade"
    return "unknown_zero"


def record_job(job_dir: Path) -> list[dict]:
    rows: list[dict] = []
    phash = prompt_hash()
    cfg = load_config()
    max_turns = cfg.get("max_turns", 40)

    for trial_dir in sorted(job_dir.iterdir()):
        if not trial_dir.is_dir():
            continue
        result_path = trial_dir / "result.json"
        if not result_path.exists():
            continue
        try:
            result = json.loads(result_path.read_text())
        except Exception as e:
            print(f"[warn] could not read {result_path}: {e}", file=sys.stderr)
            continue

        task_name = result.get("task_name", "unknown")
        trial_name = result.get("trial_name", trial_dir.name)
        reward = float(
            (result.get("verifier_result") or {}).get("rewards", {}).get("reward", 0.0)
        )
        # Trials that fail before the agent produces output (e.g. BadRequestError
        # on the first chat call) leave metadata==None, not {}. dict.get("k", {})
        # only returns the default when the key is missing, not when value is None.
        agent_result = result.get("agent_result") or {}
        metadata = agent_result.get("metadata") or {}
        gemma = metadata.get("gemma_result") or {}
        turns = int(gemma.get("turns", 0))
        trace = gemma.get("trace") or []
        status = gemma.get("status", "")
        drift_events = gemma.get("drift_events") or []
        repair_attempts = int(gemma.get("repair_attempts", 0))

        # Surface Harbor-level exceptions (BadRequestError etc.) so they aren't
        # silently hidden behind 'unknown_zero'.
        exception_info = result.get("exception_info")
        if exception_info and not status:
            exc_type = exception_info.get("exception_type", "") if isinstance(exception_info, dict) else ""
            if exc_type:
                status = f"harbor_exception:{exc_type}"

        started = result.get("started_at")
        finished = result.get("finished_at")
        runtime_sec = None
        try:
            if started and finished:
                s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                runtime_sec = (f - s).total_seconds()
        except Exception:
            pass

        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_name": job_dir.name,
            "task_name": task_name,
            "trial_name": trial_name,
            "reward": reward,
            "turns": turns,
            "max_turns": max_turns,
            "prompt_hash": phash,
            "config": cfg,
            "failure_tag": tag_failure(reward, turns, max_turns, trace, status),
            "runtime_sec": runtime_sec,
            "drift_count": len(drift_events),
            "repair_attempts": repair_attempts,
        }
        rows.append(row)
    return rows


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    job_dir = Path(sys.argv[1])
    if not job_dir.is_absolute():
        job_dir = (ROOT / job_dir).resolve()
    if not job_dir.is_dir():
        print(f"[error] not a directory: {job_dir}", file=sys.stderr)
        sys.exit(1)

    rows = record_job(job_dir)
    if not rows:
        print(f"[warn] no trials found under {job_dir}", file=sys.stderr)
        sys.exit(0)

    ledger = ROOT / "runs" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    for row in rows:
        print(
            f"[record] {row['task_name']:50s} reward={row['reward']:.2f} "
            f"turns={row['turns']:2d} drift={row['drift_count']} repair={row['repair_attempts']} tag={row['failure_tag']}"
        )


if __name__ == "__main__":
    main()
