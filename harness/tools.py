import json
import os
import re

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

_TOOLS = {
    "bash": _bash,
    "file_view": _file_view,
    "file_edit": _file_edit,
    "grep": _grep,
}

async def execute(name: str, args: dict, environment, cwd: str) -> dict:
    if name not in _TOOLS:
        return {"error": f"Unknown tool: {name!r}"}
    return await _TOOLS[name](args, environment, cwd)
