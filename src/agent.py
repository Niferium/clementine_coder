"""
agent.py — Core coding agent: model lifecycle, generation, and session state.

Owns the lazy model cache (one model in memory at a time), the per-session
conversation history, and the main generation pipeline:

    route → token_check → generate → self_check → token_check → yield tokens

One Agent instance is created at startup and shared across all Flask requests
via a module-level singleton. Thread safety for concurrent requests is handled
by a generation lock — only one generation runs at a time (matching the single
GPU constraint of mlx on Apple Silicon).
"""

from __future__ import annotations

import gc
import threading
import queue
from pathlib import Path

import mlx.core as mx
from mlx_lm import load, generate

from src.logger       import Logger
from src.skill_parser import parse_skills, generate_system_prompt
from src.router       import route_skill
from src.self_checker import run_self_check_loop
from src import token_monitor


# ── Constants ──────────────────────────────────────────────────────────────────

MAIN_MODEL    = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
ROUTER_MODEL  = "mlx-community/Qwen1.5-1.8B-Chat-4bit"
MAX_TOKENS    = 32000     # Max tokens before refusing to generate (includes history + response)
ROUTER_TOKENS = 128      # Router only needs a short JSON blob


# ── Agent ──────────────────────────────────────────────────────────────────────

class Agent:
    """
    Coding agent with skill routing, self-checking, and token monitoring.

    Lifecycle:
        agent = Agent()
        agent.startup()          ← loads router model, parses SKILL.md
        agent.process(...)       ← one turn of the chat loop

    process() returns a queue.Queue that receives SSE events (dicts with
    'event' and 'data' keys). The Flask SSE endpoint drains this queue.
    """

    def __init__(self, skill_file: Path, logger: Logger):
        self.skill_file   = skill_file
        self.logger       = logger

        # ── Lazy model cache (one model in memory at a time) ─────────────────
        self._loaded_name:      str | None = None
        self._loaded_model                 = None
        self._loaded_tokenizer             = None

        # ── Per-session state (keyed by session_id) ──────────────────────────
        # {session_id: {"history": [], "skill": str, "turn": int}}
        self._sessions: dict[str, dict] = {}

        # ── Parsed skills (loaded at startup) ────────────────────────────────
        self.skills: dict[str, dict] = {}

        # ── Generation lock — one generation at a time on Apple Silicon ──────
        self._gen_lock = threading.Lock()

    # ── Startup ───────────────────────────────────────────────────────────────

    def startup(self):
        """
        Parse SKILL.md and pre-load the router model.
        Called once at Flask server startup.
        """
        self.logger.log_header()
        self.logger.log_debug_kirbo()

        self.skills = parse_skills(self.skill_file, self.logger)
        self.logger.log_startup(MAIN_MODEL, ROUTER_MODEL, 5000)

        # Pre-load the router so the first request is fast
        self._require(ROUTER_MODEL)
        self.logger.log_model_ready(ROUTER_MODEL)

    # ── Model cache ───────────────────────────────────────────────────────────

    def _require(self, model_name: str):
        """
        Return (model, tokenizer) for model_name.

        Evicts the currently loaded model first if a different model
        is requested. Logs the swap via Logger. Uses gc.collect() and
        mx.metal.clear_cache() to free GPU memory before loading.

        Args:
            model_name: HuggingFace model ID string.

        Returns:
            (model, tokenizer) tuple.
        """
        if self._loaded_name == model_name:
            return self._loaded_model, self._loaded_tokenizer

        if self._loaded_model is not None:
            self.logger.log_model_swap(self._loaded_name, model_name)
            self._loaded_model     = None
            self._loaded_tokenizer = None
            self._loaded_name      = None
            gc.collect()
            mx.metal.clear_cache()

        self.logger.log_model_loading(model_name)
        self._loaded_model, self._loaded_tokenizer = load(model_name)
        self._loaded_name = model_name
        self.logger.log_model_ready(model_name)

        return self._loaded_model, self._loaded_tokenizer

    # ── Session management ────────────────────────────────────────────────────

    def get_session(self, session_id: str) -> dict:
        """
        Return the session dict for session_id, creating it if new.

        Session dict shape:
            {
                "history":       [],      # list of {"role", "content"} dicts
                "skill":         "general",
                "turn":          0,
                "file_injected": False,
            }
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "history":       [],
                "skill":         "general",
                "turn":          0,
                "file_injected": False,
            }
        return self._sessions[session_id]

    def clear_session(self, session_id: str):
        """Remove a session from the registry (e.g. on user logout or reset)."""
        self._sessions.pop(session_id, None)

    def get_token_count(self, session_id: str) -> int:
        """
        Return the current estimated token count for a session.
        Returns 0 if the session has no history or no model is loaded.
        """
        session = self._sessions.get(session_id)
        if not session or not self._loaded_tokenizer:
            return 0

        skill   = session.get("skill", "general")
        system  = generate_system_prompt(self.skills.get(skill, self.skills.get("general", {})))
        history = session.get("history", [])
        return token_monitor.count_history_tokens(self._loaded_tokenizer, system, history)

    # ── File injection ────────────────────────────────────────────────────────

    def inject_file(self, user_message: str, file_content: str, filename: str) -> str:
        """
        Append file content to the user message.

        Output shape:
            <user message>

            ### File: <filename>
            ```python
            <contents>
            ```

        Args:
            user_message:  The raw user input string.
            file_content:  The file contents as a string.
            filename:      The display filename (e.g. "main.py").

        Returns:
            Augmented user message string.
        """
        line_count = len(file_content.splitlines())
        self.logger.log_file_injected(filename, line_count)

        # Detect language for the code fence from file extension
        ext_to_lang = {
            ".py":   "python",
            ".js":   "javascript",
            ".ts":   "typescript",
            ".kt":   "kotlin",
            ".html": "html",
            ".css":  "css",
            ".sql":  "sql",
            ".md":   "markdown",
            ".rb":   "ruby",
            ".pl":   "perl",
            ".go":   "go",
            ".rs":   "rust",
            ".java": "java",
            ".cpp":  "cpp",
            ".c":    "c",
            ".sh":   "bash",
            ".md":   "markdown",
        }
        suffix = Path(filename).suffix.lower()
        lang   = ext_to_lang.get(suffix, "")

        return (
            f"{user_message}\n\n"
            f"### File: {filename}\n"
            f"```{lang}\n{file_content}\n```"
        )

    # ── Main pipeline ─────────────────────────────────────────────────────────

    def process(
        self,
        session_id:   str,
        user_message: str,
        file_content: str | None = None,
        filename:     str | None = None,
    ) -> queue.Queue:
        """
        Process one user turn and return a Queue that receives SSE events.

        The actual generation runs in a background thread so Flask can
        stream SSE events while generation is in progress.

        SSE event shapes emitted to the queue:
            {"event": "token",              "data": {"text": "..."}}
            {"event": "skill",              "data": {"skill": "...", "switched": bool}}
            {"event": "self_check_start",   "data": {"pass": int, "max": int}}
            {"event": "self_check_issues",  "data": {"pass": int, "issues": [...]}}
            {"event": "self_check_clean",   "data": {"pass": int}}
            {"event": "self_check_max",     "data": {"max": int}}
            {"event": "token_warning",      "data": {"current": int, "max": int}}
            {"event": "token_count",        "data": {"current": int, "max": int, "pct": float}}
            {"event": "done",               "data": {"passes": int, "issues_fixed": int}}
            {"event": "error",              "data": {"message": "..."}}

        Args:
            session_id:   Unique session identifier string.
            user_message: Raw user input string.
            file_content: Optional file contents string to inject.
            filename:     Optional display filename for file injection.

        Returns:
            A queue.Queue instance. Sentinel None signals stream end.
        """
        event_queue: queue.Queue = queue.Queue()

        thread = threading.Thread(
            target=self._generation_thread,
            args=(session_id, user_message, file_content, filename, event_queue),
            daemon=True,
        )
        thread.start()

        return event_queue

    # ── Generation thread ─────────────────────────────────────────────────────

    def _generation_thread(
        self,
        session_id:   str,
        user_message: str,
        file_content: str | None,
        filename:     str | None,
        q:            queue.Queue,
    ):
        """
        Background thread: full generation pipeline for one user turn.

        Steps:
          1. Acquire generation lock (one at a time on Apple Silicon GPU)
          2. Load router model → route skill
          3. File injection if provided
          4. Token check before generation — may summarize history
          5. Load main model → generate response (streamed to queue)
          6. Self-check loop — rewrites code blocks with # SELF-CHECK: comments
          7. Token check after generation
          8. Append final response to history
          9. Emit done event, release lock
        """
        with self._gen_lock:
            try:
                session = self.get_session(session_id)
                self.logger.log_request(session_id, session["skill"], user_message)

                # ── 1. Route skill ────────────────────────────────────────────
                router_model, router_tokenizer = self._require(ROUTER_MODEL)

                chosen_skill, switched, reason = route_skill(
                    user_message      = user_message,
                    skills            = self.skills,
                    router_model      = router_model,
                    router_tokenizer  = router_tokenizer,
                    current_skill     = session["skill"],
                    router_max_tokens = ROUTER_TOKENS,
                    logger            = self.logger,
                )

                if switched:
                    session["history"] = []   # reset history on skill change
                    session["skill"]   = chosen_skill

                q.put({"event": "skill", "data": {
                    "skill":    chosen_skill,
                    "switched": switched,
                    "reason":   reason,
                }})

                # ── 2. File injection ─────────────────────────────────────────
                if file_content and not session["file_injected"]:
                    fname        = filename or "uploaded_file"
                    user_message = self.inject_file(user_message, file_content, fname)
                    session["file_injected"] = True

                # ── 3. Load main model ────────────────────────────────────────
                main_model, main_tokenizer = self._require(MAIN_MODEL)

                # ── 4. Token check BEFORE generation ─────────────────────────
                system  = generate_system_prompt(self.skills[chosen_skill])
                history = session["history"]

                history, hard_stop = token_monitor.check_and_handle(
                    tokenizer  = main_tokenizer,
                    system     = system,
                    history    = history,
                    max_tokens = MAX_TOKENS,
                    logger     = self.logger,
                    model      = main_model,
                )
                session["history"] = history

                current_tokens = token_monitor.count_history_tokens(
                    main_tokenizer, system, history
                )
                q.put({"event": "token_count", "data": {
                    "current": current_tokens,
                    "max":     MAX_TOKENS,
                    "pct":     round(current_tokens / MAX_TOKENS * 100, 1),
                }})

                if hard_stop:
                    q.put({"event": "error", "data": {
                        "message": (
                            f"Token limit reached ({MAX_TOKENS:,}). "
                            "Please start a new session."
                        )
                    }})
                    return

                if current_tokens / MAX_TOKENS >= token_monitor.WARN_THRESHOLD:
                    q.put({"event": "token_warning", "data": {
                        "current": current_tokens,
                        "max":     MAX_TOKENS,
                    }})

                # ── 5. Append user message + generate ─────────────────────────
                session["turn"] += 1
                history.append({"role": "user", "content": user_message})

                messages = [{"role": "system", "content": system}] + history
                prompt   = main_tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )

                self.logger.log_generation_start(
                    chosen_skill, session["turn"], current_tokens, MAX_TOKENS
                )

                # Generate — collect full response for self-check
                # (SSE tokens are emitted after self-check to keep stream coherent)
                response = generate(
                    main_model,
                    main_tokenizer,
                    prompt=prompt,
                    max_tokens=MAX_TOKENS,
                    verbose=False,
                )

                # ── 6. Self-check loop ────────────────────────────────────────
                final_response, passes_run, issues_fixed = run_self_check_loop(
                    response  = response,
                    model     = main_model,
                    tokenizer = main_tokenizer,
                    logger    = self.logger,
                    max_passes= 3,
                    queue     = q,
                )

                # ── 7. Stream final response tokens to UI ─────────────────────
                # Emit the full (possibly rewritten) response in chunks
                CHUNK_SIZE = 4
                words = final_response.split(" ")
                for i in range(0, len(words), CHUNK_SIZE):
                    chunk = " ".join(words[i:i + CHUNK_SIZE])
                    if i + CHUNK_SIZE < len(words):
                        chunk += " "
                    q.put({"event": "token", "data": {"text": chunk}})

                # ── 8. Append to history ──────────────────────────────────────
                history.append({"role": "assistant", "content": final_response})
                session["history"] = history

                self.logger.log_response(final_response, session_id, session["turn"])

                # ── 9. Final token count ──────────────────────────────────────
                final_tokens = token_monitor.count_history_tokens(
                    main_tokenizer, system, history
                )
                q.put({"event": "done", "data": {
                    "passes":       passes_run,
                    "issues_fixed": issues_fixed,
                    "token_count":  final_tokens,
                    "max_tokens":   MAX_TOKENS,
                    "pct":          round(final_tokens / MAX_TOKENS * 100, 1),
                }})

            except Exception as exc:
                self.logger.log_error(f"Generation error: {exc}")
                q.put({"event": "error", "data": {"message": str(exc)}})

            finally:
                # Sentinel — tells the SSE stream the queue is exhausted
                q.put(None)
