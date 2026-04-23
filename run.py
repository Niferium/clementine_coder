"""
run.py — Entry point for the Coding Agent.

Starts the Flask web server on port 5000. The Agent is initialized
once at startup and shared across all requests. Terminal output is
log-only (via Logger) — the UI lives at http://localhost:5000.

Usage:
    python run.py
    python run.py --port 8080
    python run.py --skill analyst
"""

import argparse
from pathlib import Path

from src.agent  import Agent
from src.logger import Logger
from src.server import create_app


def main():
    parser = argparse.ArgumentParser(
        description="MLX Coding Agent — Flask UI + terminal logs"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=5000,
        help="Flask port (default: 5000)",
    )
    parser.add_argument(
        "--skill", "-s",
        type=str,
        default=None,
        help="Force a default skill for all new sessions (bypasses router for turn 1).",
    )
    args = parser.parse_args()

    logger     = Logger()
    skill_file = Path(__file__).parent / "skill.md"

    agent = Agent(skill_file=skill_file, logger=logger)
    agent.startup()

    app = create_app(agent=agent, logger=logger)

    logger.log_startup(
        main_model   = agent.MAIN_MODEL   if hasattr(agent, "MAIN_MODEL")   else "Qwen3-Coder-30B",
        router_model = agent.ROUTER_MODEL if hasattr(agent, "ROUTER_MODEL") else "Qwen1.5-1.8B",
        port         = args.port,
    )

    # Run Flask — threaded=True so SSE streams don't block each other
    app.run(
        host     = "0.0.0.0",
        port     = args.port,
        debug    = False,   # debug=True breaks SSE streaming
        threaded = True,
    )


if __name__ == "__main__":
    main()
