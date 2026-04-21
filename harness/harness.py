import json
import re
from openai import APITimeoutError
from harness.client import chat
from harness.tools import TOOL_SCHEMAS, execute
from prompts import SYSTEM_PROMPT


# Pseudo-protocol drift markup Gemma sometimes emits in assistant `content`:
#   <|channel>, <channel|>, <|tool_call>, <tool_call|>, <|thought>, <|"|>, etc.
# Echoing these back to the llama.cpp server in `messages` history causes
# HTTP 500 InternalServerError before a real reply comes back. Sanitize
# before re-feeding. See docs/DESIGN_2026-04-21_protocol_drift_defense.md.
_DRIFT_RE = re.compile(r"<\|[^\n>]*>|<[^\n|]*?\|>")

_DRIFT_LIMIT = 3  # abort the trial after this many drift-contaminated turns


def sanitize_assistant_content(msg_dict: dict) -> tuple[dict, bool]:
    """Strip drift markup from the assistant `content` field.

    Returns (msg_dict, drift_detected). If content is empty/None or carries no
    drift markup, returns the input unchanged with drift_detected=False.
    Structured `tool_calls` are never touched.
    """
    content = msg_dict.get("content")
    if not isinstance(content, str) or not content:
        return msg_dict, False
    cleaned = _DRIFT_RE.sub("", content)
    if cleaned == content:
        return msg_dict, False
    new_msg = dict(msg_dict)
    new_msg["content"] = cleaned
    return new_msg, True


async def run_agent(task, environment, cwd, config):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    model_timeout_sec = config.get("model_timeout_sec", 90)
    drift_events: list[int] = []  # turn indexes where drift was sanitized

    for turn in range(config["max_turns"]):
        try:
            resp = await chat(
                messages,
                tools=TOOL_SCHEMAS,
                temperature=config["temperature"],
                max_tokens=config["max_tokens_per_call"],
                timeout=model_timeout_sec,
            )
        except APITimeoutError:
            return {
                "status": "model_timeout",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
                "error": f"Gemma call exceeded {model_timeout_sec}s timeout",
            }

        msg = resp.choices[0].message
        msg_dict = msg.model_dump(exclude_unset=True)
        # Strip reasoning_content before re-feeding — llama.cpp rejects history
        # that carries it with thinking-mode enabled.
        msg_dict.pop("reasoning_content", None)
        # Strip protocol-drift markup before re-feeding (see module header).
        msg_dict, drift_detected = sanitize_assistant_content(msg_dict)
        if drift_detected:
            drift_events.append(turn)
            print(f"Protocol drift sanitized at turn {turn} (count={len(drift_events)})")
        messages.append(msg_dict)

        if len(drift_events) >= _DRIFT_LIMIT:
            return {
                "status": "malformed_model_output",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
            }

        if resp.choices[0].finish_reason == "stop":
            return {
                "status": "done",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
            }

        for tc in (msg.tool_calls or []):
            args = json.loads(tc.function.arguments)
            result = await execute(tc.function.name, args, environment, cwd)
            print(f"Executed {tc.function.name} -> return code {result.get('returncode')}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return {
        "status": "turn_limit",
        "turns": config["max_turns"],
        "trace": messages,
        "drift_events": drift_events,
    }
