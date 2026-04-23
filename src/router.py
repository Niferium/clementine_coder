"""
router.py — Semantic skill router using the small Qwen1.5 router model.

Sends the user message + available skill descriptions to the router model
and parses its JSON response to determine which skill should handle the
request. Falls back to the current active skill on parse failure.
"""

from __future__ import annotations
import re
import json
from typing import TYPE_CHECKING

from mlx_lm import generate

if TYPE_CHECKING:
    from src.logger import Logger


def build_router_prompt(tokenizer, user_message: str, skills: dict) -> str:
    """
    Build the prompt sent to the router model.

    The router receives a list of available skills with names and
    descriptions, plus the user's raw message. It must return ONLY a
    JSON object selecting the best skill.

    Args:
        tokenizer:    The router model's tokenizer.
        user_message: The raw user input string.
        skills:       The parsed skills dict from skill_parser.parse_skills().

    Returns:
        Formatted prompt string ready for the router model.
    """
    skill_list = "\n".join(
        f'- "{name}": {skill["description"]}'
        for name, skill in skills.items()
    )

    router_system = (
        "You are a skill router. Given a user message and a list of available skills, "
        "return ONLY a JSON object selecting the best skill.\n\n"
        "Rules:\n"
        "- Read each skill description carefully\n"
        "- Pick the skill whose description best matches what the user needs\n"
        "- If nothing specific matches, pick the default general skill\n"
        "- Return ONLY this JSON format, nothing else, no markdown:\n"
        '  {"skill": "<skill_name>", "reason": "<one sentence why>"}'
    )

    router_user = (
        f"Available skills:\n{skill_list}\n\n"
        f"User message:\n{user_message}\n\n"
        "Which skill should handle this? Respond with JSON only."
    )

    messages = [
        {"role": "system", "content": router_system},
        {"role": "user",   "content": router_user},
    ]

    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )


def route_skill(
    user_message: str,
    skills: dict,
    router_model,
    router_tokenizer,
    current_skill: str,
    router_max_tokens: int,
    logger: "Logger",
) -> tuple[str, bool, str | None]:
    """
    Ask the router model which skill best matches the user message.

    Runs the router model silently (verbose=False) and parses its JSON
    output. Falls back to current_skill on parse failure.

    Args:
        user_message:       The raw user input string.
        skills:             The parsed skills dict.
        router_model:       The loaded router mlx model.
        router_tokenizer:   The loaded router tokenizer.
        current_skill:      The currently active skill name.
        router_max_tokens:  Max tokens for the router output (typically 128).
        logger:             The Logger instance.

    Returns:
        (chosen_skill, switched, reason)
        - chosen_skill: name of the selected skill
        - switched:     True if skill changed from current_skill
        - reason:       Router's explanation string, or None
    """
    logger.log_routing(user_message)

    prompt = build_router_prompt(router_tokenizer, user_message, skills)

    raw = generate(
        router_model,
        router_tokenizer,
        prompt=prompt,
        max_tokens=router_max_tokens,
        verbose=False,
    )

    chosen_skill = _parse_router_response(raw, skills, current_skill, logger)
    reason       = _extract_reason(raw)
    switched     = chosen_skill != current_skill

    if switched:
        logger.log_skill_switch(current_skill, chosen_skill, reason)
    else:
        logger.log_skill_kept(current_skill)

    return chosen_skill, switched, reason


# ── Internal parsers ───────────────────────────────────────────────────────────

def _parse_router_response(
    raw: str,
    skills: dict,
    fallback: str,
    logger: "Logger",
) -> str:
    """
    Parse the router model's raw output into a skill name.

    Tries JSON first, then regex as a last resort. Falls back to
    *fallback* (the current active skill) on any parse failure.

    Args:
        raw:      Raw string output from the router model.
        skills:   The parsed skills dict for validation.
        fallback: Skill name to return on failure.
        logger:   The Logger instance.

    Returns:
        A valid skill name string.
    """
    # Strip common markdown code fences the model might add
    cleaned = raw.strip().strip("```json").strip("```").strip()

    try:
        data        = json.loads(cleaned)
        chosen_name = data.get("skill", "").strip().lower()
        if chosen_name in skills:
            return chosen_name
        logger.log_error(f"Router returned unknown skill '{chosen_name}', keeping '{fallback}'")
        return fallback

    except json.JSONDecodeError:
        # Regex fallback: look for "skill": "some_name" anywhere in the output
        match = re.search(r'"skill"\s*:\s*"(\w+)"', raw)
        if match:
            name = match.group(1).lower()
            if name in skills:
                return name

        logger.log_error(f"Router parse failed, keeping '{fallback}'. Raw: {raw[:80]}")
        return fallback


def _extract_reason(raw: str) -> str | None:
    """
    Extract the reason field from the router's JSON response if present.

    Args:
        raw: Raw string output from the router model.

    Returns:
        Reason string, or None if not parseable.
    """
    try:
        cleaned = raw.strip().strip("```json").strip("```").strip()
        data    = json.loads(cleaned)
        return data.get("reason")
    except Exception:
        return None
