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
            "name": "read_file_range",
            "description": (
                "Read a specific line range of a file. Prefer this over "
                "file_view on files larger than ~500 lines to avoid wasting "
                "context. If end is omitted, reads start..start+200."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "start": {"type": "integer", "description": "Start line (1-indexed)."},
                    "end": {"type": "integer", "description": "End line (inclusive). Optional; defaults to start+200."},
                },
                "required": ["path", "start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files in a directory matching an optional glob. Returns a "
                "structured list of files and subdirectories. Prefer this over "
                "`bash ls` for structured output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path. Defaults to '.'."},
                    "glob": {"type": "string", "description": "Glob pattern, e.g. '*.py'. Defaults to '*'."},
                    "recursive": {"type": "boolean", "description": "If true, recurse into subdirectories. Defaults to false."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apt_install",
            "description": (
                "Install system packages via apt-get. Runs `apt-get update` once "
                "per trial (if update=true) and then installs packages with "
                "noninteractive frontend. Preferred over bash `apt-get install` "
                "to standardize the install pattern."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Package names to install.",
                    },
                    "update": {"type": "boolean", "description": "Run apt-get update first. Defaults to true."},
                },
                "required": ["packages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": (
                "Apply a unified diff to a file. Use for multi-hunk edits where "
                "file_edit's unique-string matching fails. The diff must be in "
                "standard unified format with 3 lines of context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to patch."},
                    "diff": {"type": "string", "description": "Unified diff content."},
                },
                "required": ["path", "diff"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": (
                "Signal that the task is complete. Provide a one-line summary "
                "of what you verified (not what you built). The run ends "
                "immediately after this tool call. Use when your artifacts are "
                "in place AND you have verified them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "One-line summary of what was verified.",
                    }
                },
                "required": ["summary"],
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


async def _read_file_range(args: dict, environment, cwd: str) -> dict:
    """Read a specific line range of a file."""
    try:
        path = args["path"]
        start = int(args.get("start", 1))
        end = args.get("end")
        if end is None:
            end = start + 200
        else:
            end = int(end)
        # Use sed to extract the range
        result = await environment.exec(f"sed -n '{start},{end}p' {path}", cwd=cwd, timeout_sec=15)
        if result.return_code != 0:
            return {"error": f"read_file_range failed: {result.stderr}", "returncode": result.return_code}
        # Also get total line count for reference
        wc = await environment.exec(f"wc -l < {path}", cwd=cwd, timeout_sec=5)
        total = int((wc.stdout or "0").strip()) if wc.return_code == 0 else None
        return {
            "content": result.stdout,
            "range": [start, end],
            "total_lines": total,
        }
    except Exception as e:
        return {"error": str(e), "returncode": -1}


async def _list_files(args: dict, environment, cwd: str) -> dict:
    """List files in a directory matching a glob."""
    try:
        path = args.get("path", ".")
        glob_pat = args.get("glob", "*")
        recursive = bool(args.get("recursive", False))
        if recursive:
            cmd = f"find {path} -name '{glob_pat}' -printf '%y %p\\n' 2>/dev/null | head -200"
        else:
            cmd = f"find {path} -maxdepth 1 -name '{glob_pat}' -printf '%y %p\\n' 2>/dev/null | head -200"
        result = await environment.exec(cmd, cwd=cwd, timeout_sec=15)
        files = []
        dirs = []
        for line in (result.stdout or "").splitlines():
            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue
            kind, p = parts
            if kind == "f":
                files.append(p)
            elif kind == "d":
                dirs.append(p)
        return {"files": files, "dirs": dirs, "truncated": len(files) + len(dirs) >= 200}
    except Exception as e:
        return {"error": str(e), "returncode": -1}


async def _apt_install(args: dict, environment, cwd: str) -> dict:
    """Install packages via apt-get."""
    try:
        packages = args.get("packages", [])
        if not packages:
            return {"error": "no packages specified"}
        update = bool(args.get("update", True))
        pkg_str = " ".join(packages)
        env_prefix = "DEBIAN_FRONTEND=noninteractive"
        if update:
            cmd = f"{env_prefix} apt-get update -qq && {env_prefix} apt-get install -y -qq {pkg_str}"
        else:
            cmd = f"{env_prefix} apt-get install -y -qq {pkg_str}"
        result = await environment.exec(cmd, cwd=cwd, timeout_sec=180)
        return {
            "ok": result.return_code == 0,
            "installed": packages if result.return_code == 0 else [],
            "returncode": result.return_code,
            "stderr": (result.stderr or "")[:500],
        }
    except Exception as e:
        return {"error": str(e), "returncode": -1}


async def _apply_patch(args: dict, environment, cwd: str) -> dict:
    """Apply a unified diff to a file via `patch -p0`."""
    import base64
    try:
        path = args["path"]
        diff = args.get("diff", "") or ""
        b64 = base64.b64encode(diff.encode("utf-8")).decode("ascii")
        # Write diff to a temp file, run patch
        cmd = (
            f"TMPDIFF=$(mktemp); "
            f"printf %s '{b64}' | base64 -d > $TMPDIFF; "
            f"patch -p0 {path!r} < $TMPDIFF 2>&1; RC=$?; "
            f"rm -f $TMPDIFF; exit $RC"
        )
        result = await environment.exec(cmd, cwd=cwd, timeout_sec=30)
        return {
            "ok": result.return_code == 0,
            "returncode": result.return_code,
            "output": (result.stdout or "")[:500],
            "stderr": (result.stderr or "")[:500],
        }
    except Exception as e:
        return {"error": str(e), "returncode": -1}


async def _done(args: dict, environment, cwd: str) -> dict:
    """Signal task completion. The harness special-cases this to terminate."""
    return {"ok": True, "summary": args.get("summary", ""), "terminated_by": "done"}


_TOOLS = {
    "bash": _bash,
    "file_view": _file_view,
    "file_edit": _file_edit,
    "grep": _grep,
    "write_file": _write_file,
    "python": _python,
    "r": _r,
    "read_file_range": _read_file_range,
    "list_files": _list_files,
    "apt_install": _apt_install,
    "apply_patch": _apply_patch,
    "done": _done,
}

async def execute(name: str, args: dict, environment, cwd: str) -> dict:
    if name not in _TOOLS:
        return {"error": f"Unknown tool: {name!r}"}
    return await _TOOLS[name](args, environment, cwd)
