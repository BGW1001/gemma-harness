import json
import os
import re

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a bash command in the task working directory. Use for "
                "compiling, running tests, listing files, and executing "
                "scripts already present. For writing substantial code, "
                "prefer write_file; for short Python snippets, prefer python. "
                "Avoid embedding multi-line programs in heredocs."
            ),
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
            "name": "write_file",
            "description": (
                "Write content verbatim to a file (overwriting if it exists). "
                "Creates parent directories. Use this to land program source "
                "code, configuration files, or multi-line text on disk, then "
                "run it with bash. Preferred over bash heredocs for anything "
                "longer than a few lines."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path (absolute or relative to cwd).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Exact file content. No escaping required.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python",
            "description": (
                "Run a Python 3 program given as a string. Use for short "
                "computations, data inspection, and one-off scripts. "
                "For programs longer than ~30 lines, prefer write_file then "
                "bash so the code is on disk and debuggable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python 3 source code to execute.",
                    }
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "r",
            "description": (
                "Run an R program given as a string via Rscript. Use for "
                "statistical computations. For programs longer than ~30 lines, "
                "prefer write_file then bash."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "R source code to execute.",
                    }
                },
                "required": ["code"],
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

async def _bash(args: dict, environment, cwd: str) -> dict:
    cmd = args["cmd"]
    try:
        # We assume `environment` is a Harbor BaseEnvironment
        # If it's none, we are running in local mode (not supported anymore)
        result = await environment.exec(
            cmd,
            cwd=cwd,
            timeout_sec=30,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.return_code,
        }
    except Exception as e:
        return {"error": str(e), "returncode": -1}

async def _file_view(args: dict, environment, cwd: str) -> dict:
    try:
        path = args["path"]
        # Use exec to cat the file since BaseEnvironment doesn't have read_file
        result = await environment.exec(f"cat {path}", cwd=cwd)
        if result.return_code != 0:
            return {"error": f"File not found or error reading: {result.stderr}"}
        content = result.stdout or ""
        return {"content": content, "lines": content.count("\n") + 1}
    except Exception as e:
        return {"error": str(e)}

async def _file_edit(args: dict, environment, cwd: str) -> dict:
    try:
        path = args["path"]
        old_text = args["old_text"]
        new_text = args["new_text"]
        
        # Read the file first
        read_res = await environment.exec(f"cat {path}", cwd=cwd)
        if read_res.return_code != 0:
            return {"error": f"File not found or error reading: {read_res.stderr}"}
        
        content = read_res.stdout or ""
        count = content.count(old_text)
        if count == 0:
            return {"error": "old_text not found in file"}
        if count > 1:
            return {"error": f"old_text found {count} times — must be unique"}
            
        new_content = content.replace(old_text, new_text, 1)
        
        # Write back - we need to be careful with quotes, so maybe upload a file
        import tempfile
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(new_content)
            temp_path = f.name
            
        # upload_file(source_path, target_path)
        # However, target_path needs to be absolute or relative to environment.
        # Harbor's upload_file uses absolute paths inside the container, or we can use exec with base64.
        import base64
        b64_content = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
        write_res = await environment.exec(f"echo '{b64_content}' | base64 -d > {path}", cwd=cwd)
        
        os.unlink(temp_path)
        
        if write_res.return_code != 0:
            return {"error": f"Error writing file: {write_res.stderr}"}
            
        return {"ok": True, "path": path}
    except Exception as e:
        return {"error": str(e)}

async def _grep(args: dict, environment, cwd: str) -> dict:
    pattern = args["pattern"]
    search_path = args.get("path", ".")
    try:
        # Escape pattern single quotes
        safe_pattern = pattern.replace("'", "'\\''")
        result = await environment.exec(
            f"grep -rn --include=* '{safe_pattern}' {search_path}",
            cwd=cwd,
            timeout_sec=15,
        )
        # grep returns 1 if no lines selected, which is fine
        if result.return_code not in (0, 1):
             return {"error": f"grep error: {result.stderr}"}
             
        matches = (result.stdout or "").strip().splitlines()
        return {
            "matches": matches,
            "count": len(matches),
        }
    except Exception as e:
        return {"error": str(e)}

async def _write_file(args: dict, environment, cwd: str) -> dict:
    """Write content verbatim to path, creating parent dirs. Overwrites.

    Uses base64 over stdin so arbitrary bytes (quotes, newlines, braces) are
    preserved through the shell without escaping concerns.
    """
    import base64
    try:
        path = args["path"]
        content = args.get("content", "") or ""
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        # mkdir -p of the parent dir (portable); then decode into target
        cmd = f"mkdir -p \"$(dirname -- {path!r})\" && printf %s '{b64}' | base64 -d > {path!r}"
        result = await environment.exec(cmd, cwd=cwd, timeout_sec=30)
        if result.return_code != 0:
            return {"error": f"write_file failed: {result.stderr}", "returncode": result.return_code}
        return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        return {"error": str(e), "returncode": -1}


async def _python(args: dict, environment, cwd: str) -> dict:
    """Execute Python 3 code via stdin. Avoids shell-escaping concerns."""
    import base64
    try:
        code = args.get("code", "") or ""
        b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
        cmd = f"printf %s '{b64}' | base64 -d | python3"
        result = await environment.exec(cmd, cwd=cwd, timeout_sec=60)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.return_code,
        }
    except Exception as e:
        return {"error": str(e), "returncode": -1}


async def _r(args: dict, environment, cwd: str) -> dict:
    """Execute R code via Rscript stdin."""
    import base64
    try:
        code = args.get("code", "") or ""
        b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
        # Rscript reads from stdin with "-" when given no script path
        cmd = f"printf %s '{b64}' | base64 -d | Rscript -"
        result = await environment.exec(cmd, cwd=cwd, timeout_sec=60)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.return_code,
        }
    except Exception as e:
        return {"error": str(e), "returncode": -1}


_TOOLS = {
    "bash": _bash,
    "file_view": _file_view,
    "file_edit": _file_edit,
    "grep": _grep,
    "write_file": _write_file,
    "python": _python,
    "r": _r,
}

async def execute(name: str, args: dict, environment, cwd: str) -> dict:
    if name not in _TOOLS:
        return {"error": f"Unknown tool: {name!r}"}
    return await _TOOLS[name](args, environment, cwd)
