import json
import re
from openai import APITimeoutError, BadRequestError, InternalServerError, APIError
from harness.client import chat
from harness.tools import TOOL_SCHEMAS, execute
from prompts import SYSTEM_PROMPT


# Pseudo-protocol drift markup Gemma sometimes emits in assistant `content`:
#   <|channel>, <channel|>, <|tool_call>, <tool_call|>, <|thought>, <|"|>, etc.
# Echoing these back to the llama.cpp server in `messages` history causes
# HTTP 500 InternalServerError before a real reply comes back. Sanitize
# before re-feeding. See docs/DESIGN_2026-04-21_protocol_drift_defense.md.
#
# As of Track A remediation (2026-04-22):
# - sanitization remains as defense-in-depth and instrumentation
# - retry-with-repair (A.5) is now wired in: when drift is detected with no
#   real tool_calls, we inject a synthetic repair message and let the model
#   self-correct, rather than silently continue or immediately abort.
# - repair_attempts is tracked separately from drift_events in the result.
_DRIFT_RE = re.compile(r"<\|[^\n>]*>|<[^\n|]*?\|>")

_DRIFT_LIMIT = 3   # abort the trial after this many drift-contaminated turns
_REPAIR_BUDGET = 2  # max synthetic repair injections per trial

_REPAIR_REASON = (
    "Your previous response included internal channel markup "
    "(<|channel|>, <|tool_call|>, <|thought|>, <|\"|>, or similar) in the "
    "text content. The system cannot parse that as a real tool call. "
    "If you need to run a command or read a file, use the actual tool "
    "interface. If you are done, emit only plain text with no markup."
)


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


def _has_real_tool_calls(msg) -> bool:
    """Return True if the message has at least one structured tool_calls entry."""
    tc = getattr(msg, "tool_calls", None)
    return bool(tc)


async def run_agent(task, environment, cwd, config):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    model_timeout_sec = config.get("model_timeout_sec", 90)
    drift_events: list[int] = []   # turn indexes where drift markup was sanitized
    repair_attempts: int = 0       # number of synthetic repair injections made

    for turn in range(config["max_turns"]):
        try:
            resp = await chat(
                messages,
                tools=TOOL_SCHEMAS,
                temperature=config["temperature"],
                max_tokens=config["max_tokens_per_call"],
                timeout=model_timeout_sec,
            )
        except InternalServerError as e:
            # Server-side 500 — typically llama.cpp failing to parse the model's
            # tool_call arguments as JSON when arguments contain unescaped braces
            # (PYEOF heredocs, JSON snippets, etc.). Known llama.cpp issue #21384.
            # These are deterministic on the current conversation state; retry
            # won't help. Terminate cleanly so Harbor doesn't mark it as an
            # uncaught exception.
            return {
                "status": "server_tool_parse_error",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
                "repair_attempts": repair_attempts,
                "error": str(e)[:500],
            }
        except BadRequestError as e:
            # Server-side 400 — covers any edge cases not caught by the
            # finish_reason=length guard below (e.g., prefill-continuation on
            # thinking-mode templates, context overflow).
            return {
                "status": "server_bad_request",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
                "repair_attempts": repair_attempts,
                "error": str(e)[:500],
            }
        except APITimeoutError:
            return {
                "status": "model_timeout",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
                "repair_attempts": repair_attempts,
                "error": f"Gemma call exceeded {model_timeout_sec}s timeout",
            }

        msg = resp.choices[0].message
        msg_dict = msg.model_dump(exclude_unset=True)
        # Strip reasoning_content before re-feeding — llama.cpp rejects history
        # that carries it with thinking-mode enabled.
        msg_dict.pop("reasoning_content", None)
        # Strip protocol-drift markup before re-feeding (defense-in-depth).
        msg_dict, drift_detected = sanitize_assistant_content(msg_dict)
        if drift_detected:
            drift_events.append(turn)
            print(f"Protocol drift sanitized at turn {turn} (count={len(drift_events)})")

        messages.append(msg_dict)

        # Hard abort: too many drift events even after sanitization.
        if len(drift_events) >= _DRIFT_LIMIT:
            return {
                "status": "malformed_model_output",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
                "repair_attempts": repair_attempts,
            }

        finish_reason = resp.choices[0].finish_reason
        has_tools = _has_real_tool_calls(msg)

        # --- Retry-with-repair (Track A / A.5) ---
        # When the model emits drift markup but no real tool_calls and claims
        # it is done (finish_reason == "stop"), it almost certainly tried to
        # fake a tool call in content. Inject an explicit repair message so
        # the model can self-correct rather than failing silently.
        if drift_detected and not has_tools and finish_reason == "stop":
            if repair_attempts < _REPAIR_BUDGET:
                repair_attempts += 1
                print(
                    f"Injecting repair message at turn {turn} "
                    f"(repair_attempt={repair_attempts})"
                )
                messages.append({
                    "role": "user",
                    "content": f"[tool_use_failed] {_REPAIR_REASON}",
                })
                continue  # re-enter loop without consuming a real turn slot
            else:
                # Repair budget exhausted.
                return {
                    "status": "malformed_model_output",
                    "turns": turn,
                    "trace": messages,
                    "drift_events": drift_events,
                    "repair_attempts": repair_attempts,
                }

        # Normal stop: model is done.
        if finish_reason == "stop":
            return {
                "status": "done",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
                "repair_attempts": repair_attempts,
            }

        # Truncation with no tool calls → terminate, don't loop back into a
        # prefill-continuation request. Qwen3.6 + thinking-mode can emit long
        # reasoning_content that hits max_tokens_per_call before any tool call;
        # looping back would send a messages[] ending in an assistant role, which
        # the server rejects with "Assistant response prefill is incompatible
        # with enable_thinking". Better to stop cleanly and surface the cause.
        if not has_tools and finish_reason != "stop":
            return {
                "status": "output_truncated",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
                "repair_attempts": repair_attempts,
                "finish_reason": finish_reason,
            }

        # Execute tool calls. On malformed tool-call JSON (Qwen3.6 occasionally
        # emits unterminated strings in function.arguments), inject a synthetic
        # tool result explaining the parse error and let the model self-correct
        # on the next turn, rather than crashing the trial.
        done_called = False
        done_summary = ""
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError) as e:
                err_msg = f"tool_args_parse_error: {e}. Retry with valid JSON in function.arguments."
                print(f"Tool-args parse error at turn {turn}: {e}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"error": err_msg, "returncode": -1}),
                })
                continue
            result = await execute(tc.function.name, args, environment, cwd)
            rc = result.get("returncode")
            print(f"Executed {tc.function.name} -> return code {rc}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })
            # Special-case the done() tool: after executing it, terminate the
            # loop. The run ends with the verifier check on whatever state the
            # trial container is in.
            if tc.function.name == "done":
                done_called = True
                done_summary = str(args.get("summary", ""))[:500]

        if done_called:
            return {
                "status": "done_explicit",
                "turns": turn,
                "trace": messages,
                "drift_events": drift_events,
                "repair_attempts": repair_attempts,
                "done_summary": done_summary,
            }

    return {
        "status": "turn_limit",
        "turns": config["max_turns"],
        "trace": messages,
        "drift_events": drift_events,
        "repair_attempts": repair_attempts,
    }
