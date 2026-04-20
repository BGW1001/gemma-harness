#!/usr/bin/env python3
import tempfile
import yaml
import os
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.harness import run

def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    task = "Write a file called 'hello.txt' containing exactly the text 'Hello from Gemma!'. Then finish."

    with tempfile.TemporaryDirectory() as tempdir:
        print(f"Running trivial task in temp dir: {tempdir}")
        result = run(task, cwd=tempdir, config=config)

        print(f"Status: {result['status']}")
        print(f"Turns: {result['turns']}")

        filepath = os.path.join(tempdir, "hello.txt")
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            print(f"\nSUCCESS! File found. Content: {content!r}")
        else:
            print("\nFAILURE! File not found.")
            print(f"Dir contents: {os.listdir(tempdir)}")

        print("\nTrace:")
        for msg in result.get('trace', []):
            if hasattr(msg, 'model_dump'):
                msg = msg.model_dump(exclude_unset=True)
            elif hasattr(msg, 'dict'):
                msg = msg.dict()

            role = msg.get('role', 'unknown')
            if role == 'user':
                print(f"[{role}] {msg.get('content', '')[:100]}...")
            elif role == 'assistant':
                if 'tool_calls' in msg and msg['tool_calls']:
                    for tc in msg['tool_calls']:
                        try:
                            # In Pydantic models, function might be an object
                            func = tc.get('function', {})
                            if not isinstance(func, dict):
                                func = {"name": getattr(func, "name"), "arguments": getattr(func, "arguments")}
                            print(f"[{role}] -> calls {func.get('name')}({func.get('arguments')})")
                        except Exception as e:
                            print(f"[{role}] -> calls (error formatting: {e})")
                else:
                    print(f"[{role}] {str(msg.get('content', ''))[:100]}...")
            elif role == 'tool':
                print(f"[{role}] <- {str(msg.get('content', ''))[:100]}...")

if __name__ == "__main__":
    main()
