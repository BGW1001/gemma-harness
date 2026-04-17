"""
Tool schemas and implementations for the Gemma harness.

Phase 1 tools:
  - bash(cmd)           — run a shell command in cwd
  - file_view(path)     — read a file
  - file_edit(path, old_text, new_text) — exact-match replace
  - grep(pattern, path) — search for pattern in files

Safety:
  - file operations are restricted to within cwd
  - bash runs in cwd with a 30s timeout
"""

import json
import os
import re
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# OpenAI tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a bash command in the task working directory. Use for compiling, running tests, listing files, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {
                        "type": "string",
                        "description": "The bash command to run.",
                    }
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_view",
            "description": "Read and return the full contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file, relative to the working directory.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_edit",
            "description": (
                "Replace an exact string in a file with new text. "
                "old_text must match exactly (including whitespace). "
                "Fails if old_text is not found or matches multiple locations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to working directory."},
                    "old_text": {"type": "string", "description": "Exact text to find and replace."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search for a regex pattern in files under a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for."},
                    "path": {
                        "type": "string",
                        "description": "File or directory to search (relative to working directory). Defaults to '.'.",
                        "default": ".",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------

def _safe_path(raw_path: str, cwd: str) -> Path:
    """Resolve path and ensure it stays inside cwd."""
    base = Path(cwd).resolve()
    target = (base / raw_path).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"Path escape attempt: {raw_path!r} resolves outside cwd {cwd!r}")
    return target

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _bash(args: dict, cwd: str) -> dict:
    cmd = args["cmd"]
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 30 seconds", "returncode": -1}
    except Exception as e:
        return {"error": str(e), "returncode": -1}


def _file_view(args: dict, cwd: str) -> dict:
    try:
        path = _safe_path(args["path"], cwd)
        if not path.exists():
            return {"error": f"File not found: {args['path']}"}
        if not path.is_file():
            return {"error": f"Not a file: {args['path']}"}
        content = path.read_text(errors="replace")
        return {"content": content, "lines": content.count("\n") + 1}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def _file_edit(args: dict, cwd: str) -> dict:
    try:
        path = _safe_path(args["path"], cwd)
        old_text = args["old_text"]
        new_text = args["new_text"]
        if not path.exists():
            return {"error": f"File not found: {args['path']}"}
        content = path.read_text(errors="replace")
        count = content.count(old_text)
        if count == 0:
            return {"error": "old_text not found in file"}
        if count > 1:
            return {"error": f"old_text found {count} times — must be unique"}
        new_content = content.replace(old_text, new_text, 1)
        path.write_text(new_content)
        return {"ok": True, "path": str(path)}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def _grep(args: dict, cwd: str) -> dict:
    pattern = args["pattern"]
    search_path = args.get("path", ".")
    try:
        safe = _safe_path(search_path, cwd)
        result = subprocess.run(
            ["grep", "-rn", "--include=*", pattern, str(safe)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        matches = result.stdout.strip().splitlines()
        return {
            "matches": matches,
            "count": len(matches),
        }
    except ValueError as e:
        return {"error": str(e)}
    except subprocess.TimeoutExpired:
        return {"error": "grep timed out"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_TOOLS = {
    "bash": _bash,
    "file_view": _file_view,
    "file_edit": _file_edit,
    "grep": _grep,
}


def execute(name: str, args: dict, cwd: str) -> dict:
    if name not in _TOOLS:
        return {"error": f"Unknown tool: {name!r}"}
    return _TOOLS[name](args, cwd)
