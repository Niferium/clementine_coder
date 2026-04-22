from logger import Logger
from pathlib import Path
import re
import json
import sys
import argparse
import gc
import mlx.core as mx
from mlx_lm import load, generate

class Main:
    def __init__(self):
        self.logger = Logger()
        self.MAIN_MODEL   = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"

        # Router model — small, fast, only used for skill selection
        # Swap for any small Qwen3 instruct model you have locally
        self.ROUTER_MODEL = "mlx-community/Qwen1.5-1.8B-Chat-4bit"

        self.SKILL_FILE   = Path(__file__).parent / "SKILL.md"
        self.MAX_TOKENS   = 4096
        self.ROUTER_TOKENS = 128          # router only needs to output a short JSON blob

        # ── Lazy model cache (one model in memory at a time) ──────────────────────────

        self._loaded_name:      str | None = None
        self._loaded_model                 = None
        
    def _require(self, model_name: str):
        """Return (model, tokenizer) for *model_name*, evicting any other loaded model first."""

        if self._loaded_name == model_name:
            return self._loaded_model, self._loaded_tokenizer

        if self._loaded_model is not None:
            print(f"   🔄 Unloading {self._loaded_name}...")
            self._loaded_model     = None
            self._loaded_tokenizer = None
            self._loaded_name      = None
            gc.collect()
            mx.metal.clear_cache()

        print(f"   📦 Loading {model_name}...")
        self._loaded_model, self._loaded_tokenizer = load(model_name)
        self._loaded_name = model_name
        return self._loaded_model, self._loaded_tokenizer

    # ─────────────────────────────────────────────────────────────────────────────
    # SKILL.md Parser
    # ─────────────────────────────────────────────────────────────────────────────

    def parse_skills(self, skill_file: Path) -> dict[str, dict]:
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
                    "body":        "<full markdown of this skill section>"
                },
                "analyst": { ... }
            }
        """
        if not skill_file.exists():
            print(f"[ERROR] SKILL.md not found: {skill_file}")
            sys.exit(1)

        raw     = skill_file.read_text(encoding="utf-8")
        pattern = re.compile(r"^## Skill:\s*(\w+)", re.MULTILINE)
        matches = list(pattern.finditer(raw))

        if not matches:
            print("[ERROR] No '## Skill:' sections found in SKILL.md.")
            sys.exit(1)

        skills = {}

        for i, match in enumerate(matches):
            name       = match.group(1).strip().lower()
            body_start = match.end()
            body_end   = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            body       = raw[body_start:body_end].strip()

            trigger     = self._extract_meta(body, "trigger")     or ("default" if name == "general" else name)
            description = self._extract_meta(body, "description") or ""

            skills[name] = {
                "name":        name,
                "trigger":     trigger,
                "description": description,
                "body":        body,
            }
            print(f"[SKILL] Parsed: '{name}' — {description[:60]}...")

        return skills


    def _extract_meta(self, body: str, key: str) -> str | None:
        """Extract **key**: value from skill body metadata lines."""
        match = re.search(
            rf"^\*\*{key}\*\*:\s*(.+)$", body,
            flags=re.MULTILINE | re.IGNORECASE
        )
        return match.group(1).strip() if match else None


    # ─────────────────────────────────────────────────────────────────────────────
    # System Prompt Generator
    # ─────────────────────────────────────────────────────────────────────────────

    def generate_system_prompt(self, skill: dict) -> str:
        """
        Build a clean system prompt from a parsed skill block.
        Strips SKILL.md metadata lines so only instructions reach the model.
        """
        body = skill["body"]

        # Remove metadata lines (**trigger**: ..., **description**: ...)
        body = re.sub(
            r"^\*\*(trigger|description)\*\*:.*$\n?", "",
            body, flags=re.MULTILINE | re.IGNORECASE
        )
        # Remove horizontal rules
        body = re.sub(r"^---\s*\n", "", body, flags=re.MULTILINE)
        body = body.strip()

        return f"# Active Skill: {skill['name'].title()}\n\n{body}"


    # ─────────────────────────────────────────────────────────────────────────────
    # Semantic Skill Router
    # ─────────────────────────────────────────────────────────────────────────────

    def build_router_prompt(self, tokenizer, user_message: str, skills: dict) -> str:
        """
        Build the prompt sent to the router model.

        The router receives:
        - A list of available skills with their names and descriptions
        - The user's message
        - Instructions to return a JSON object with the best skill name

        It must return ONLY valid JSON: {"skill": "<name>", "reason": "<why>"}
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
        self,
        user_message: str,
        skills: dict,
        router_model,
        router_tokenizer,
        current_skill: str,
    ) -> tuple[str, bool]:
        """
        Ask the router model which skill best matches the user message.

        Returns:
            (skill_name, switched) — skill_name is the chosen skill,
            switched=True if it differs from current_skill.
        """
        prompt = self.build_router_prompt(router_tokenizer, user_message, skills)

        raw = generate(
            router_model,
            router_tokenizer,
            prompt=prompt,
            max_tokens=self.ROUTER_TOKENS,
            verbose=False,          # silent — router output isn't shown to user
        )

        # Parse the JSON response
        chosen_skill = self._parse_router_response(raw, skills, current_skill)

        switched = chosen_skill != current_skill
        if switched:
            reason = self._extract_router_reason(raw)
            print(f"\n[ROUTER] '{current_skill}' → '{chosen_skill}'")
            if reason:
                print(f"[ROUTER] Reason: {reason}\n")

        return chosen_skill, switched


    def _parse_router_response(self, raw: str, skills: dict, fallback: str) -> str:
        """
        Safely extract the skill name from the router's JSON response.
        Falls back to the current skill if parsing fails or skill is unknown.
        """
        # Strip any accidental markdown fences
        raw = raw.strip().strip("```json").strip("```").strip()

        try:
            data         = json.loads(raw)
            chosen_name  = data.get("skill", "").strip().lower()
            if chosen_name in skills:
                return chosen_name
            else:
                print(f"[ROUTER] Unknown skill '{chosen_name}', keeping '{fallback}'")
                return fallback
        except json.JSONDecodeError:
            # Try to extract skill name with regex as last resort
            match = re.search(r'"skill"\s*:\s*"(\w+)"', raw)
            if match:
                name = match.group(1).lower()
                if name in skills:
                    return name
            print(f"[ROUTER] Failed to parse response, keeping '{fallback}'")
            print(f"[ROUTER] Raw response was: {raw[:100]}")
            return fallback


    def _extract_router_reason(self, raw: str) -> str | None:
        """Pull the reason field from the router's JSON response if present."""
        try:
            raw   = raw.strip().strip("```json").strip("```").strip()
            data  = json.loads(raw)
            return data.get("reason")
        except Exception:
            return None


    # ─────────────────────────────────────────────────────────────────────────────
    # File Injection
    # ─────────────────────────────────────────────────────────────────────────────

    def read_script(self, file_path: str) -> str:
        """
        Read a Python script from a local path.
        Tries UTF-8 first, falls back to latin-1.
        """
        path = Path(file_path)
        if not path.exists():
            print(f"[ERROR] File not found: {file_path}")
            sys.exit(1)

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
            print("[INFO] Encoding fallback: latin-1")

        print(f"[INFO] Loaded: {path.name} ({len(content.splitlines())} lines)")
        return content


    def inject_file(self, user_message: str, file_path: str) -> str:
        """
        Append a script's full contents into the user message.

        Output shape:
            <user message>

            ### File: script.py
            ```python
            <contents>
            ```
        """
        content   = self.read_script(file_path)
        file_name = Path(file_path).name
        return (
            f"{user_message}\n\n"
            f"### File: {file_name}\n"
            f"```python\n{content}\n```"
        )


    # ─────────────────────────────────────────────────────────────────────────────
    # Prompt Builder
    # ─────────────────────────────────────────────────────────────────────────────

    def build_prompt(self, tokenizer, system: str, history: list[dict]) -> str:
        """Render the full prompt using the tokenizer's chat template."""
        messages = [{"role": "system", "content": system}] + history
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )


    # ─────────────────────────────────────────────────────────────────────────────
    # Main Chat Loop
    # ─────────────────────────────────────────────────────────────────────────────

    def chat(self, file_path: str | None = None, start_skill: str | None = None):

        # ── Parse SKILL.md ───────────────────────────────────────────────────────
        skills = self.parse_skills(self.SKILL_FILE)

        # ── 1st Load router model ────────────────────────────────────────────────────
        print(f"\n[INFO] Loading router: {self.ROUTER_MODEL}")
        _loaded_model, _loaded_tokenizer = self._require(self.ROUTER_MODEL)
        print("[INFO] Router ready.")

        

        # ── Session state ────────────────────────────────────────────────────────
        # If --skill was passed, bypass router for the first turn
        force_skill   = start_skill if start_skill and start_skill in skills else None
        active_skill  = force_skill or "general"
        history: list[dict] = []
        file_injected = False

        # ── Banner ───────────────────────────────────────────────────────────────
        print("=" * 60)
        print("  Coding Agent  |  semantic routing via LLM router")
        print(f"  Active skill  : {active_skill}")
        print(f"  Router model  : {self.ROUTER_MODEL}")
        print(f"  Main model    : {self.MAIN_MODEL}")
        if file_path:
            print(f"  File queued   : {file_path}")
        if force_skill:
            print(f"  Router        : bypassed (forced skill: {force_skill})")
        print("=" * 60 + "\n")

        while True:
            # ── Input ────────────────────────────────────────────────────────────
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[INFO] Exiting.")
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", "q"}:
                print("[INFO] Goodbye.")
                break

            # ── Semantic skill routing ───────────────────────────────────────────
            if force_skill:
                # First turn only — use forced skill, then hand off to router
                chosen_skill = force_skill
                switched     = False
                force_skill  = None       # router takes over from next turn
            else:
                print("[ROUTER] Routing...", end=" ", flush=True)
                chosen_skill, switched = self.route_skill(
                    user_input,
                    skills,
                    _loaded_model,
                    _loaded_tokenizer,
                    active_skill,
                )
                if not switched:
                    print(f"keeping '{active_skill}'")

            if switched:
                active_skill = chosen_skill
                history      = []         # reset history on skill change
                print("[INFO] History cleared for new skill context.\n")
            else:
                active_skill = chosen_skill

            # ── File injection (first message only) ──────────────────────────────
            if file_path and not file_injected:
                user_input    = self.inject_file(user_input, file_path)
                file_injected = True
                print("[INFO] Script injected into message.\n")

            # ── Build prompt & generate ──────────────────────────────────────────
            
            # ── Load main model ──────────────────────────────────────────────────────
            print(f"[INFO] Loading main model: {self.MAIN_MODEL}")
            _loaded_model, _loaded_tokenizer = self._require(self.MAIN_MODEL)
            print("[INFO] Main model ready.\n")
            history.append({"role": "user", "content": user_input})

            system = self.generate_system_prompt(skills[active_skill])
            prompt = self.build_prompt(_loaded_tokenizer, system, history)

            print(f"\nAssistant [{active_skill}]: ", end="", flush=True)

            response = generate(
                _loaded_model,
                _loaded_tokenizer,
                prompt=prompt,
                max_tokens = self.MAX_TOKENS,
                verbose=True,
            )
            print("\n")

            history.append({"role": "assistant", "content": response})
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MLX coding agent with semantic LLM-based skill routing."
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Path to a Python script to inject into the first user message.",
    )
    parser.add_argument(
        "--skill", "-s",
        type=str,
        default=None,
        help=(
            "Force a specific skill for the first turn, bypassing the router. "
            "Router takes over from turn 2 onwards. "
            "Must match a '## Skill:' name in SKILL.md."
        ),
    )
    args = parser.parse_args()
    main = Main()
    main.chat(file_path=args.file, start_skill=args.skill)
    