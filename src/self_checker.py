"""
self_checker.py — Dynamic self-check loop for generated code.

After the main model produces a response, this module:
1. Extracts all code blocks from the response.
2. Sends each code block back to the main model with a strict reviewer prompt.
3. The reviewer returns a JSON list of issues: [{line, severity, type, suggestion}]
4. If issues are found, a rewrite pass is triggered with # SELF-CHECK: comments
   injected above changed lines so both agents and humans can follow the reasoning.
5. The loop repeats until either no issues are found OR MAX_SELF_CHECK_PASSES is hit.

The final response returned has the improved code baked in with all
# SELF-CHECK: annotations visible in the code blocks.
"""

from __future__ import annotations
import re
import json
from typing import TYPE_CHECKING

from mlx_lm import generate

if TYPE_CHECKING:
    from src.logger import Logger


# ── Constants ──────────────────────────────────────────────────────────────────

MAX_SELF_CHECK_PASSES = 3   # Default max passes before giving up


# ── System prompts ─────────────────────────────────────────────────────────────

REVIEWER_SYSTEM = """You are a senior software engineer code reviewer. Your job is to review a code block and return a JSON array of issues found.

For each issue return:
  {"line": <line_number_int>, "severity": "high|medium|low", "type": "bug|security|style|optimization", "suggestion": "<what to fix and how>"}

Rules:
- Always read the code carefully and fully before responding. Do not make assumptions.
- Only flag REAL issues — not stylistic preferences unless clearly wrong
- "high" severity = bugs, security flaws, broken logic
- "medium" severity = architectural issues, missing error handling, bad patterns
- "low" severity = naming, minor style, small optimizations
- If no issues found, return an empty array: []
- Return ONLY the JSON array. No markdown, no preamble, no explanation.
"""

REWRITER_SYSTEM = """You are a senior software engineer. You will receive a code block and a list of issues to fix.

For EVERY change you make, add a comment on the line ABOVE the changed line in this format:
    SELF-CHECK [SEVERITY]: <type> — <brief reason for the change>

Example:
    SELF-CHECK [HIGH]: security — sanitized user input before passing to subprocess
    result = subprocess.run(shlex.split(safe_input), ...)

Rules:
- Always read the issues carefully and fully before making ANY changes. Do not make assumptions.
- Fix ALL issues listed. Do not skip any.
- Add a comment based on how did you fix it and what is the reason for the fix on EVERY changed line or block.
- Make ONLY the necessary changes to fix the issues. Do not rewrite the entire block.
- Return ONLY the fixed code block — no markdown fences, no explanation.
- Preserve all existing comments and docstrings.
- Keep line structure consistent with the original unless a fix requires restructuring.
"""


# ── Public API ─────────────────────────────────────────────────────────────────

def run_self_check_loop(
    response: str,
    model,
    tokenizer,
    logger: "Logger",
    max_passes: int = MAX_SELF_CHECK_PASSES,
    queue=None,
) -> tuple[str, int, int]:
    """
    Run the dynamic self-check loop on a model response.

    Extracts code blocks from the response, reviews each for issues,
    rewrites with # SELF-CHECK: comments if needed, and repeats until
    clean or max_passes is reached.

    Args:
        response:   The full assistant response string containing code blocks.
        model:      The loaded main mlx model (used for review + rewrite).
        tokenizer:  The loaded main tokenizer.
        logger:     The Logger instance.
        max_passes: Max review/rewrite iterations (default: 3).
        queue:      Optional queue.Queue for SSE events to the web UI.

    Returns:
        (final_response, passes_run, issues_fixed_total)
    """
    code_blocks = _extract_code_blocks(response)

    if not code_blocks:
        # No code in this response — skip self-check entirely
        return response, 0, 0

    current_response  = response
    total_issues_fixed = 0

    for pass_num in range(1, max_passes + 1):
        logger.log_self_check_start(pass_num, max_passes)

        if queue:
            _emit(queue, "self_check_start", {"pass": pass_num, "max": max_passes})

        # Re-extract code blocks from current (possibly rewritten) response
        code_blocks = _extract_code_blocks(current_response)

        pass_had_issues = False
        updated_response = current_response

        for lang, code in code_blocks:
            issues = _review_code_block(code, model, tokenizer)

            if not issues:
                continue

            pass_had_issues = True
            total_issues_fixed += len(issues)
            logger.log_self_check_issues(pass_num, issues)

            if queue:
                _emit(queue, "self_check_issues", {
                    "pass":   pass_num,
                    "issues": issues,
                })

            # Rewrite the code block with # SELF-CHECK: comments
            fixed_code = _rewrite_code_block(code, issues, model, tokenizer)

            if fixed_code:
                # Replace the old code block with the fixed one in the full response
                old_block = _format_code_block(lang, code)
                new_block = _format_code_block(lang, fixed_code)
                updated_response = updated_response.replace(old_block, new_block, 1)

        current_response = updated_response

        if not pass_had_issues:
            logger.log_self_check_clean(pass_num)
            if queue:
                _emit(queue, "self_check_clean", {"pass": pass_num})
            break
    else:
        # Exited loop without a clean pass — max passes reached
        logger.log_self_check_max_reached(max_passes)
        if queue:
            _emit(queue, "self_check_max", {"max": max_passes})

    return current_response, pass_num, total_issues_fixed


# ── Internal: code block extraction ───────────────────────────────────────────

def _extract_code_blocks(response: str) -> list[tuple[str, str]]:
    """
    Extract all fenced code blocks from a response string.

    Matches blocks like:
        ```python
        <code>
        ```

    Also matches blocks with no language specifier (treated as 'text').

    Args:
        response: The full assistant response string.

    Returns:
        List of (language, code_content) tuples.
    """
    pattern = re.compile(
        r"```(\w*)\n(.*?)```",
        re.DOTALL,
    )
    blocks = []
    for match in pattern.finditer(response):
        lang = match.group(1).strip() or "text"
        code = match.group(2)
        blocks.append((lang, code))
    return blocks


def _format_code_block(lang: str, code: str) -> str:
    """Format a (lang, code) tuple back into a markdown fenced code block."""
    return f"```{lang}\n{code}```"


# ── Internal: reviewer ─────────────────────────────────────────────────────────

def _review_code_block(
    code: str,
    model,
    tokenizer,
) -> list[dict]:
    """
    Send a code block to the main model for review.

    The reviewer returns a JSON array of issue dicts. This function
    parses and validates that array.

    Args:
        code:      The raw code string to review.
        model:     The loaded main mlx model.
        tokenizer: The loaded main tokenizer.

    Returns:
        List of issue dicts. Empty list if no issues or parse failure.
    """
    prompt = tokenizer.apply_chat_template(
        [
            {"role": "system", "content": REVIEWER_SYSTEM},
            {"role": "user",   "content": f"Review this code:\n\n{code}"},
        ],
        tokenize=False,
        add_generation_prompt=True,
    )

    raw = generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=512,
        verbose=False,
    )

    return _parse_issues(raw)


def _parse_issues(raw: str) -> list[dict]:
    """
    Parse the reviewer's raw output into a list of issue dicts.

    Tries JSON first. Falls back to regex extraction if the model
    wrapped the array in markdown fences.

    Args:
        raw: Raw string output from the reviewer model.

    Returns:
        List of issue dicts. Empty list on parse failure.
    """
    cleaned = raw.strip().strip("```json").strip("```").strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            # Validate each issue has required fields; drop malformed ones
            valid = []
            for item in data:
                if isinstance(item, dict) and "suggestion" in item:
                    valid.append({
                        "line":       item.get("line", 0),
                        "severity":   item.get("severity", "low").lower(),
                        "type":       item.get("type", "style"),
                        "suggestion": item.get("suggestion", ""),
                    })
            return valid
        return []

    except (json.JSONDecodeError, ValueError):
        # Last resort: check if the model returned an empty array signal
        if "[]" in cleaned or cleaned in ("", "[]"):
            return []
        # Cannot parse — treat as no issues to avoid false rewrites
        return []


# ── Internal: rewriter ─────────────────────────────────────────────────────────

def _rewrite_code_block(
    code: str,
    issues: list[dict],
    model,
    tokenizer,
) -> str | None:
    """
    Rewrite a code block with # SELF-CHECK: comments for each fix.

    Sends the code + issue list to the main model with the rewriter
    system prompt. The model returns only the fixed code (no fences).

    Args:
        code:      The original code string.
        issues:    List of issue dicts from _review_code_block().
        model:     The loaded main mlx model.
        tokenizer: The loaded main tokenizer.

    Returns:
        Fixed code string, or None if rewrite failed.
    """
    issues_text = "\n".join(
        f"- Line {i.get('line', '?')} [{i['severity'].upper()}] {i['type']}: {i['suggestion']}"
        for i in issues
    )

    user_content = (
        f"Fix all issues listed below in this code block. "
        f"Add SELF-CHECK comments as instructed.\n\n"
        f"Issues to fix:\n{issues_text}\n\n"
        f"Code:\n{code}"
    )

    prompt = tokenizer.apply_chat_template(
        [
            {"role": "system", "content": REWRITER_SYSTEM},
            {"role": "user",   "content": user_content},
        ],
        tokenize=False,
        add_generation_prompt=True,
    )

    fixed = generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=2048,
        verbose=False,
    )

    fixed = fixed.strip()

    # Strip any markdown fences the model might have added despite instructions
    if fixed.startswith("```"):
        fixed = re.sub(r"^```\w*\n?", "", fixed)
        fixed = re.sub(r"\n?```$", "", fixed)
        fixed = fixed.strip()

    return fixed if fixed else None


# ── SSE helper ─────────────────────────────────────────────────────────────────

def _emit(queue, event: str, data: dict):
    """
    Push a self-check SSE event into the response queue.

    Args:
        queue: A queue.Queue instance shared with the SSE stream.
        event: Event name string (e.g. "self_check_start").
        data:  Dict payload serialized to JSON in the SSE handler.
    """
    try:
        queue.put_nowait({"event": event, "data": data})
    except Exception:
        pass  # Never let SSE queue errors crash the check loop
