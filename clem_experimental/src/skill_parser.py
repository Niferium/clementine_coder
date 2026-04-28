"""
skill_parser.py — SKILL.md parser and system prompt builder.

Reads the combined SKILL.md file and splits it into individual
skill blocks. Each block is parsed for metadata (trigger, description)
and its cleaned body is used to build the system prompt sent to the
main model.
"""

import re
import sys
from pathlib import Path


def parse_skills(skill_file: Path, logger) -> dict[str, dict]:
    """
    Parse a combined SKILL.md into a dict of skill blocks.

    Each skill is delimited by:
        ## Skill: <name>

    Returns:
        {
            "general": {
                "name":        "general",
                "trigger":     "default",
                "description": "...",
                "body":        "<full markdown body of this skill section>"
            },
            ...
        }

    Exits the process if the file is missing or has no skill sections.
    """
    if not skill_file.exists():
        logger.log_error(f"SKILL.md not found: {skill_file}")
        sys.exit(1)

    raw     = skill_file.read_text(encoding="utf-8")
    pattern = re.compile(r"^## Skill:\s*(\w+)", re.MULTILINE)
    matches = list(pattern.finditer(raw))

    if not matches:
        logger.log_error("No '## Skill:' sections found in SKILL.md.")
        sys.exit(1)

    skills: dict[str, dict] = {}

    for i, match in enumerate(matches):
        name       = match.group(1).strip().lower()
        body_start = match.end()
        body_end   = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body       = raw[body_start:body_end].strip()

        trigger     = _extract_meta(body, "trigger")     or ("default" if name == "general" else name)
        description = _extract_meta(body, "description") or ""

        skills[name] = {
            "name":        name,
            "trigger":     trigger,
            "description": description,
            "body":        body,
        }

    return skills


def _extract_meta(body: str, key: str) -> str | None:
    """
    Extract **key**: value from a skill body's metadata lines.

    Metadata lines follow the format:
        **trigger**: default
        **description**: General-purpose coding assistant...

    Returns the stripped value string, or None if not found.
    """
    match = re.search(
        rf"^\*\*{key}\*\*:\s*(.+)$",
        body,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def generate_system_prompt(skill: dict) -> str:
    """
    Build a clean system prompt from a parsed skill block.

    Strips SKILL.md metadata lines (trigger, description) and horizontal
    rules so only the instruction content reaches the model. Prepends a
    skill identity header so the model knows which skill is active.

    Args:
        skill: A parsed skill dict from parse_skills().

    Returns:
        A clean string ready to use as the system message.
    """
    body = skill["body"]

    # Remove metadata lines: **trigger**: ..., **description**: ...
    body = re.sub(
        r"^\*\*(trigger|description)\*\*:.*$\n?",
        "",
        body,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Remove markdown horizontal rules
    body = re.sub(r"^---\s*\n", "", body, flags=re.MULTILINE)

    body = body.strip()

    return f"# Active Skill: {skill['name'].title()}\n\n{body}"
