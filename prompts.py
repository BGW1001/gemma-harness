"""
Composes the system prompt from editable markdown artifacts.

Editable surface (AutoResearch mutates these):
  prompts/system.md          — operating contract
  skills/*.md                — named playbooks
  policies/*.md              — behavioral rules

Harness (harness/harness.py) imports SYSTEM_PROMPT from here.
"""

from pathlib import Path

_ROOT = Path(__file__).parent


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except FileNotFoundError:
        return ""


def _compose() -> str:
    parts = []

    system = _read(_ROOT / "prompts" / "system.md")
    if system:
        parts.append(system)

    skills_dir = _ROOT / "skills"
    if skills_dir.is_dir():
        for p in sorted(skills_dir.glob("*.md")):
            body = _read(p)
            if body:
                parts.append(body)

    policies_dir = _ROOT / "policies"
    if policies_dir.is_dir():
        for p in sorted(policies_dir.glob("*.md")):
            body = _read(p)
            if body:
                parts.append(body)

    return "\n\n---\n\n".join(parts) if parts else "You are a terminal-task-solving agent."


SYSTEM_PROMPT = _compose()

# Legacy vars retained for any external import. Now dead in harness.
PLAN_PROMPT = ""
REFLECT_PROMPT = ""
