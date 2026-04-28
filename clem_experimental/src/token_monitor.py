"""
token_monitor.py — Token counting, 80% warning, and history summarizer.

Tracks token usage across the conversation history. At 80% of MAX_TOKENS,
it triggers a graceful history summarization using the main model to free
context space. At 100% it issues a hard stop and blocks generation.

Token counts are estimated by encoding the full prompt string with the
loaded tokenizer — this matches what mlx_lm actually sees.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.logger import Logger


# ── Constants ──────────────────────────────────────────────────────────────────

WARN_THRESHOLD  = 0.80   # Warn and summarize at 80% capacity
HARD_THRESHOLD  = 1.00   # Hard stop at 100%


# ── Public helpers ─────────────────────────────────────────────────────────────

def count_tokens(tokenizer, text: str) -> int:
    """
    Count the number of tokens in *text* using the loaded tokenizer.

    Uses the tokenizer's encode method directly so the count matches
    what mlx_lm will actually see during generation.

    Args:
        tokenizer: The loaded mlx_lm tokenizer.
        text:      The string to count tokens for.

    Returns:
        Integer token count.
    """
    # encode() returns a list of token ids; len gives the count
    return len(tokenizer.encode(text))


def count_history_tokens(tokenizer, system: str, history: list[dict]) -> int:
    """
    Estimate total token usage for a system prompt + conversation history.

    Concatenates all content strings with role prefixes to produce a
    representative string, then counts tokens. This avoids applying the
    full chat template (which requires add_generation_prompt=True and may
    differ slightly) but is accurate enough for monitoring purposes.

    Args:
        tokenizer: The loaded mlx_lm tokenizer.
        system:    The system prompt string.
        history:   List of {"role": ..., "content": ...} message dicts.

    Returns:
        Estimated integer token count.
    """
    parts = [f"[system]\n{system}"]
    for msg in history:
        parts.append(f"[{msg['role']}]\n{msg['content']}")
    combined = "\n\n".join(parts)
    return count_tokens(tokenizer, combined)


def check_and_handle(
    tokenizer,
    system: str,
    history: list[dict],
    max_tokens: int,
    logger: "Logger",
    model=None,
) -> tuple[list[dict], bool]:
    """
    Check current token usage and handle threshold breaches.

    Behavior:
    - Below 80%:  Return history unchanged. No action.
    - At 80–99%:  Log warning, run history summarization, return compressed history.
    - At 100%+:   Log hard stop, return history unchanged, set hard_stop=True.

    Args:
        tokenizer:  The loaded mlx_lm tokenizer.
        system:     The active system prompt.
        history:    The current conversation history list.
        max_tokens: The configured MAX_TOKENS ceiling.
        logger:     The Logger instance for terminal output.
        model:      The main model (needed for summarization). If None, skip summarize.

    Returns:
        (updated_history, hard_stop)
        hard_stop=True means generation must be blocked.
    """
    current = count_history_tokens(tokenizer, system, history)
    ratio   = current / max_tokens

    logger.log_token_status(current, max_tokens)

    if ratio >= HARD_THRESHOLD:
        logger.log_token_hard_stop(max_tokens)
        return history, True

    if ratio >= WARN_THRESHOLD:
        logger.log_token_warning(current, max_tokens)
        if model is not None and len(history) > 2:
            history = _summarize_history(model, tokenizer, history, logger)
            after   = count_history_tokens(tokenizer, system, history)
            logger.log_history_summarized(current, after)

    return history, False


# ── Internal: history summarizer ──────────────────────────────────────────────

def _summarize_history(model, tokenizer, history: list[dict], logger) -> list[dict]:
    """
    Compress conversation history using the main model.

    Takes all but the last two turns (to preserve immediate context),
    summarizes them into a single assistant-role summary turn, and
    prepends that to the last two turns.

    The resulting history is shorter but retains the most recent context
    and a condensed memory of earlier turns.

    Args:
        model:     The loaded mlx_lm main model.
        tokenizer: The loaded mlx_lm tokenizer.
        history:   The full conversation history list.
        logger:    The Logger instance.

    Returns:
        Compressed history list.
    """
    from mlx_lm import generate  # local import to avoid circular dependency

    # Keep the last 2 turns intact — summarize everything before them
    preserve_tail = history[-2:] if len(history) >= 2 else history
    to_summarize  = history[:-2] if len(history) >= 2 else []

    if not to_summarize:
        # Nothing old enough to summarize — return unchanged
        return history

    # Build a plain-text transcript of the turns to summarize
    transcript_parts = []
    for msg in to_summarize:
        role    = msg["role"].upper()
        content = msg["content"][:500]  # cap each turn to avoid recursion
        transcript_parts.append(f"[{role}]: {content}")
    transcript = "\n\n".join(transcript_parts)

    summary_prompt = tokenizer.apply_chat_template(
        [
            {
                "role":    "system",
                "content": (
                    "You are a conversation summarizer. "
                    "Summarize the following conversation history in under 150 tokens. "
                    "Preserve key decisions, code changes, and file names. "
                    "Output only the summary, no preamble."
                ),
            },
            {
                "role":    "user",
                "content": f"Summarize this history:\n\n{transcript}",
            },
        ],
        tokenize=False,
        add_generation_prompt=True,
    )

    summary_text = generate(
        model,
        tokenizer,
        prompt=summary_prompt,
        max_tokens=200,
        verbose=False,
    )

    # Build compressed history: summary turn + preserved tail
    compressed_history = [
        {
            "role":    "assistant",
            "content": f"[Conversation summary — earlier turns compressed]\n{summary_text.strip()}",
        }
    ] + preserve_tail

    return compressed_history
