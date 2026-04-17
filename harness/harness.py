import json
from harness.client import chat
from harness.tools import TOOL_SCHEMAS, execute
from prompts import SYSTEM_PROMPT


def run(task, cwd, config):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    for turn in range(config["max_turns"]):
        resp = chat(
            messages, tools=TOOL_SCHEMAS,
            temperature=config["temperature"],
            max_tokens=config["max_tokens_per_call"],
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_unset=True))

        if resp.choices[0].finish_reason == "stop":
            return {"status": "done", "turns": turn, "trace": messages}

        for tc in (msg.tool_calls or []):
            args = json.loads(tc.function.arguments)
            result = execute(tc.function.name, args, cwd)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return {"status": "turn_limit", "turns": config["max_turns"], "trace": messages}
