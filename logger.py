from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich.live import Live
from rich.spinner import Spinner
from rich import box
import textwrap
from datetime import datetime

class Logger:
    def __init__(self):
        self.console = Console()
        self.COLORS = {
            "human":       "bold cyan",
            "agent":       "bold magenta",
            "system":      "bold yellow",
            "rag":         "bold green",
            "llm":         "bold blue",
            "clarify":     "bold orange3",
            "error":       "bold red",
            "dim":         "dim white",
        }
        
    def _now(self) -> str:
        return datetime.now().strftime("%H:%M:%S")
    
    def log_header(self):
            self.console.print()
            self.console.print(Rule(
                "[bold white]🤖  RAG AGENT  [dim]mlx_lm · Qwen 30B Instruct[/dim][/bold white]",
                style="bright_black"
            ))
            self.console.print()

    def log_request(self, requestor: str, requestor_type: str, query: str):
        color = self.COLORS.get(requestor_type, "white")
        icon  = "👤" if requestor_type == "human" else "🤖"
        summary = textwrap.shorten(query, width=80, placeholder="…")
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column(style="dim", width=12)
        table.add_column()
        table.add_row("From",    f"[{color}]{icon} {requestor}[/{color}]  [{self.COLORS['dim']}]({requestor_type})[/{self.COLORS['dim']}]")
        table.add_row("Time",    f"[{self.COLORS['dim']}]{self._now()}[/{self.COLORS['dim']}]")
        table.add_row("Query",   f"[white]{summary}[/white]")
        self.console.print(Panel(table, title="[bold white]📥 Incoming Request[/bold white]", border_style="bright_black"))

    def log_rag(self, chunks: list[str], sufficient: bool):
        icon  = "✅" if sufficient else "⚠️ "
        label = "Sufficient context" if sufficient else "Insufficient context"
        color = self.COLORS["rag"] if sufficient else self.COLORS["clarify"]
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column(style="dim", width=12)
        table.add_column()
        table.add_row("Status",  f"[{color}]{icon} {label}[/{color}]")
        table.add_row("Chunks",  f"[{self.COLORS['dim']}]{len(chunks)} retrieved[/{self.COLORS['dim']}]")
        for i, c in enumerate(chunks, 1):
            table.add_row(f"  [{i}]", f"[{self.COLORS['dim']}]{textwrap.shorten(c, 70, placeholder='…')}[/{self.COLORS['dim']}]")
        self.console.print(Panel(table, title="[bold green]📚 RAG Retrieval[/bold green]", border_style="green"))

    def log_thinking(self):
        """Returns a Rich Live context for the spinner."""
        return Live(
            Spinner("dots", text=Text(" LLM thinking…", style="bold blue")),
            console=self.console,
            transient=True,
        )

    def log_response(self, answer: str, session_id: str, turn: int):
        self.console.print(Panel(
            f"[white]{answer.strip()}[/white]",
            title=f"[bold blue]💬 Agent Response  [dim]session={session_id[:8]}  turn={turn}[/dim][/bold blue]",
            border_style="blue",
        ))

    def log_clarification(self, question: str):
        self.console.print(Panel(
            f"[bold orange3]{question.strip()}[/bold orange3]",
            title="[bold orange3]❓ Clarification Needed[/bold orange3]",
            border_style="orange3",
        ))

    def log_error(self, msg: str):
        self.console.print(Panel(f"[bold red]{msg}[/bold red]", title="[bold red]💥 Error[/bold red]", border_style="red"))

    def log_debug(self, msg: str):
        self.console.print()
        self.console.print(Panel(
            f"[bold violet]************DEBUG************* {msg} [/bold violet]"
        , border_style="violet"))
        self.console.print()

    def log_debug_kirbo(self):
        self.console.print()
        self.console.print(Panel("""[bold orange3]  while you wait, Kirbo but orange!                                                                                
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
                    @@@@@@@@                       @@@@@@@   [/bold orange3]"""
        , border_style="orange3"))
        self.console.print()

    def log_clementine(self):
        self.console.print()
        self.console.print(Panel("""[bold orange3]
                                  ____ _     _____ __  __ _____ _   _ _____ ___ _   _ _____ 
                                / ___| |   | ____|  \/  | ____| \ | |_   _|_ _| \ | | ____|
                                | |   | |   |  _| | |\/| |  _| |  \| | | |  | ||  \| |  _|  
                                | |___| |___| |___| |  | | |___| |\  | | |  | || |\  | |___ 
                                \____|_____|_____|_|  |_|_____|_| \_| |_| |___|_| \_|_____|
                                 [/bold orange3]""", border_style="orange3"))
        self.console.print()