"""
logger.py — Rich terminal logger for the Coding Agent.

All terminal output routes through this class. Zero raw print() calls
in production paths. Each method maps to a specific agent event so
the terminal stays readable and structured even during multi-pass
self-checking and model swaps.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich.live import Live
from rich.spinner import Spinner
from rich.progress import Progress, BarColumn, TextColumn, MofNCompleteColumn
from rich import box
import textwrap
from datetime import datetime


class Logger:
    """Structured Rich terminal logger. One instance shared across all modules."""

    def __init__(self):
        self.console = Console()
        self.COLORS = {
            "human":    "bold cyan",
            "agent":    "bold magenta",
            "system":   "bold yellow",
            "rag":      "bold green",
            "llm":      "bold blue",
            "clarify":  "bold orange3",
            "error":    "bold red",
            "dim":      "dim white",
            "success":  "bold green",
            "warning":  "bold yellow",
            "check":    "bold violet",
            "router":   "bold cyan",
            "token":    "bold bright_blue",
        }

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _now(self) -> str:
        """Return current time as HH:MM:SS string."""
        return datetime.now().strftime("%H:%M:%S")

    def _shorten(self, text: str, width: int = 80) -> str:
        """Shorten text with ellipsis for panel display."""
        return textwrap.shorten(text, width=width, placeholder="…")

    # ── Startup ───────────────────────────────────────────────────────────────

    def log_header(self):
        """Print the startup banner rule."""
        self.console.print()
        self.console.print(Rule(
            "[bold white]🤖  CODING AGENT  "
            "[dim]mlx_lm · Qwen3 Coder 30B + Qwen1.5 Router[/dim][/bold white]",
            style="bright_black"
        ))
        self.console.print()

    def log_startup(self, main_model: str, router_model: str, port: int):
        """Log agent startup config as a summary table."""
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column(style="dim", width=16)
        table.add_column()
        table.add_row("Main Model",   f"[bold blue]{main_model}[/bold blue]")
        table.add_row("Router Model", f"[bold cyan]{router_model}[/bold cyan]")
        table.add_row("Flask Port",   f"[bold white]http://localhost:{port}[/bold white]")
        table.add_row("Terminal",     "[dim]Log-only mode — UI at Flask URL above[/dim]")
        self.console.print(Panel(
            table,
            title="[bold white]🚀 Agent Starting[/bold white]",
            border_style="bright_black"
        ))

    # ── Model lifecycle ───────────────────────────────────────────────────────

    def log_model_loading(self, model_name: str):
        """Log that a model is being loaded from disk."""
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"📦 Loading [bold]{model_name}[/bold]…"
        )

    def log_model_ready(self, model_name: str):
        """Log that a model is ready for inference."""
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['success']}]✅ Ready:[/{self.COLORS['success']}] "
            f"[bold]{model_name}[/bold]"
        )

    def log_model_swap(self, evicting: str, loading: str):
        """Log a model eviction + load swap."""
        self.console.print()
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column(style="dim", width=12)
        table.add_column()
        table.add_row("Evicting", f"[{self.COLORS['warning']}]{evicting}[/{self.COLORS['warning']}]")
        table.add_row("Loading",  f"[{self.COLORS['llm']}]{loading}[/{self.COLORS['llm']}]")
        self.console.print(Panel(
            table,
            title="[bold yellow]🔄 Model Swap[/bold yellow]",
            border_style="yellow"
        ))

    # ── Routing ───────────────────────────────────────────────────────────────

    def log_routing(self, user_message: str):
        """Log that skill routing is starting."""
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['router']}]🔀 Routing:[/{self.COLORS['router']}] "
            f"{self._shorten(user_message, 60)}"
        )

    def log_skill_switch(self, from_skill: str, to_skill: str, reason: str | None = None):
        """Log a skill change with optional router reason."""
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column(style="dim", width=12)
        table.add_column()
        table.add_row("From",   f"[{self.COLORS['warning']}]{from_skill}[/{self.COLORS['warning']}]")
        table.add_row("To",     f"[{self.COLORS['success']}]{to_skill}[/{self.COLORS['success']}]")
        if reason:
            table.add_row("Reason", f"[{self.COLORS['dim']}]{self._shorten(reason, 70)}[/{self.COLORS['dim']}]")
        self.console.print(Panel(
            table,
            title="[bold cyan]🎯 Skill Switch[/bold cyan]",
            border_style="cyan"
        ))

    def log_skill_kept(self, skill: str):
        """Log that the active skill was kept unchanged."""
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['router']}]🎯 Skill kept:[/{self.COLORS['router']}] "
            f"[bold]{skill}[/bold]"
        )

    # ── Generation ────────────────────────────────────────────────────────────

    def log_thinking(self):
        """Return a Rich Live spinner context for LLM inference."""
        return Live(
            Spinner("dots", text=Text(" LLM generating…", style="bold blue")),
            console=self.console,
            transient=True,
        )

    def log_generation_start(self, skill: str, turn: int, token_count: int, max_tokens: int):
        """Log the start of a main model generation pass."""
        self.console.print(
            f"\n   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['llm']}]⚡ Generating[/{self.COLORS['llm']}] "
            f"[dim]skill={skill}  turn={turn}  tokens={token_count}/{max_tokens}[/dim]"
        )

    def log_response(self, answer: str, session_id: str, turn: int):
        """Log the final assistant response."""
        self.console.print(Panel(
            f"[white]{answer.strip()}[/white]",
            title=(
                f"[bold blue]💬 Agent Response  "
                f"[dim]session={session_id[:8]}  turn={turn}[/dim][/bold blue]"
            ),
            border_style="blue",
        ))

    # ── Self-check ────────────────────────────────────────────────────────────

    def log_self_check_start(self, pass_num: int, max_passes: int):
        """Log the start of a self-check pass."""
        self.console.print(
            f"\n   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['check']}]🔍 Self-check pass {pass_num}/{max_passes}…"
            f"[/{self.COLORS['check']}]"
        )

    def log_self_check_issues(self, pass_num: int, issues: list[dict]):
        """Log issues found in a self-check pass, color-coded by severity."""
        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        table.add_column("Line",       style="dim",        width=6)
        table.add_column("Severity",   width=10)
        table.add_column("Type",       width=12)
        table.add_column("Suggestion")

        severity_colors = {
            "high":   "bold red",
            "medium": "bold yellow",
            "low":    "bold green",
        }

        for issue in issues:
            sev   = issue.get("severity", "low").lower()
            color = severity_colors.get(sev, "white")
            table.add_row(
                str(issue.get("line", "?")),
                f"[{color}]{sev.upper()}[/{color}]",
                issue.get("type", "unknown"),
                # self._shorten(issue.get("suggestion", ""), 60),
                issue.get("suggestion", "")
            )

        self.console.print(Panel(
            table,
            title=f"[bold violet]🔍 Self-Check Pass {pass_num} — {len(issues)} issue(s) found[/bold violet]",
            border_style="violet"
        ))

    def log_self_check_clean(self, pass_num: int):
        """Log that a self-check pass found no issues — loop stops."""
        self.console.print(Panel(
            f"[{self.COLORS['success']}]✅ No issues found on pass {pass_num}. "
            f"Self-check complete.[/{self.COLORS['success']}]",
            title="[bold green]🔍 Self-Check — Clean[/bold green]",
            border_style="green"
        ))

    def log_self_check_max_reached(self, max_passes: int):
        """Log that max self-check passes were reached."""
        self.console.print(Panel(
            f"[{self.COLORS['warning']}]⚠️  Max passes ({max_passes}) reached. "
            f"Finalizing with last revision.[/{self.COLORS['warning']}]",
            title="[bold yellow]🔍 Self-Check — Max Passes[/bold yellow]",
            border_style="yellow"
        ))

    # ── Token monitoring ──────────────────────────────────────────────────────

    def log_token_status(self, current: int, max_tokens: int):
        """Log current token usage inline (called each turn)."""
        pct = (current / max_tokens) * 100
        color = (
            self.COLORS["error"]   if pct >= 100 else
            self.COLORS["warning"] if pct >= 80  else
            self.COLORS["success"]
        )
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['token']}]🔢 Tokens:[/{self.COLORS['token']}] "
            f"[{color}]{current:,} / {max_tokens:,} ({pct:.0f}%)[/{color}]"
        )

    def log_token_warning(self, current: int, max_tokens: int):
        """Log the 80% token capacity warning."""
        self.console.print(Panel(
            f"[{self.COLORS['warning']}]⚠️  Token usage at "
            f"{current:,} / {max_tokens:,} — above 80% threshold.\n"
            f"Summarizing conversation history to free context space…"
            f"[/{self.COLORS['warning']}]",
            title="[bold yellow]🔢 Token Warning — Summarizing History[/bold yellow]",
            border_style="yellow"
        ))

    def log_token_hard_stop(self, max_tokens: int):
        """Log a hard stop when the token limit is fully hit."""
        self.console.print(Panel(
            f"[{self.COLORS['error']}]🚨 Token limit ({max_tokens:,}) reached.\n"
            f"Cannot generate. Please start a new session.[/{self.COLORS['error']}]",
            title="[bold red]🔢 Token Limit — Hard Stop[/bold red]",
            border_style="red"
        ))

    def log_history_summarized(self, before: int, after: int):
        """Log the result of history summarization."""
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['success']}]✅ History compressed:[/{self.COLORS['success']}] "
            f"[dim]{before:,} → {after:,} tokens[/dim]"
        )

    # ── File injection ────────────────────────────────────────────────────────

    def log_file_injected(self, filename: str, line_count: int):
        """Log that a file was injected into the user message."""
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['rag']}]📄 File injected:[/{self.COLORS['rag']}] "
            f"[bold]{filename}[/bold] [dim]({line_count} lines)[/dim]"
        )

    # ── Errors & misc ─────────────────────────────────────────────────────────

    def log_error(self, msg: str):
        """Log an error in a red panel."""
        self.console.print(Panel(
            f"[bold red]{msg}[/bold red]",
            title="[bold red]💥 Error[/bold red]",
            border_style="red"
        ))

    def log_clarification(self, question: str):
        """Log a clarification request from the agent."""
        self.console.print(Panel(
            f"[bold orange3]{question.strip()}[/bold orange3]",
            title="[bold orange3]❓ Clarification Needed[/bold orange3]",
            border_style="orange3",
        ))

    def log_request(self, session_id: str, skill: str, query: str):
        """Log an incoming request from the web UI."""
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column(style="dim", width=12)
        table.add_column()
        table.add_row("Session", f"[{self.COLORS['dim']}]{session_id[:8]}[/{self.COLORS['dim']}]")
        table.add_row("Time",    f"[{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}]")
        table.add_row("Skill",   f"[{self.COLORS['agent']}]{skill}[/{self.COLORS['agent']}]")
        table.add_row("Query",   f"[white]{self._shorten(query)}[/white]")
        self.console.print(Panel(
            table,
            title="[bold white]📥 Incoming Request[/bold white]",
            border_style="bright_black"
        ))

    def log_sse_event(self, event: str, data_preview: str = ""):
        """Log an SSE event being sent to the client (debug-level)."""
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[dim]→ SSE [{event}] {self._shorten(data_preview, 40)}[/dim]"
        )

    def log_debug_kirbo(self):
        """The one and only Kirbo. Called on startup."""
        self.console.print()
        self.console.print(Panel(
            """[bold orange3]  while you wait, Kirbo but orange!                                                                                
                            @@@@@@@@@@@@@@@@@@@@@@@                          
                        @@@@@@@@                @@@@@@@@                      
                      @@@@@                          @@@@@                    
                    @@@@                                @@@@                  
                  @@@                     @@ @@@          @@@                 
                 @@@                  @@   @@@              @@@               
               @@@               @@@@@@@@@@                  @@@              
               @@                                             @@@             
              @@@                                      @  @@  @@@             
             @@@       @   @                           @@@@   @@@             
             @@@       @@@@                                    @@             
             @@                                                @@@            
            @@@                                                @@@            
            @@@                                                @@@            
            @@@                                                @@@            
             @@                                               @@@             
             @@@                                              @@@             
              @@@                                            @@@              
               @@@                                          @@@               
                 @@@@                                     @@@@                
                   @@@@@                               @@@@@                  
                      @@@@@@@                     @@@@@@@@                    
                           @@@@@@@@@@@@@@@@@@@@@@@@@@@@                       
                    @@@@@@@@                       @@@@@@@   [/bold orange3]""",
            border_style="orange3"
        ))
        self.console.print()

    def log_debug(self, msg: str):
        """Log a debug message in dim text."""
        self.console.print(
            f"   [{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}] "
            f"[{self.COLORS['dim']}]DEBUG:[/{self.COLORS['dim']}] {msg}"
        )
