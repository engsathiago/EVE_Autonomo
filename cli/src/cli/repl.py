from pathlib import Path

from agent.config import get_settings
from agent.core import AgentResult, AIAgent
from agent.events import AgentEvent
from agent.tools.registry import ToolRegistry, register_builtin
from agent.transports import AnthropicTransport
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markup import escape
from rich.text import Text

console = Console()

_HISTORY_FILE = Path.home() / ".agent_history"
_COMMANDS = {"/clear", "/exit", "/cost", "/tools"}


def _prompt_toolbar() -> HTML:
    settings = get_settings()
    return HTML(f"<b>modelo:</b> {settings.agent.default_model}")


async def run_repl() -> None:
    settings = get_settings()

    registry = ToolRegistry()
    register_builtin(registry)

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(_HISTORY_FILE)),
        bottom_toolbar=_prompt_toolbar,
    )

    console.print(
        f"\n[bold cyan]Eve[/bold cyan] [dim]v{settings.agent.default_model}[/dim]"
        " — [dim]/exit para sair, /help para comandos[/dim]\n"
    )

    # Rastreia custo acumulado da sessão
    session_input_tokens = 0
    session_output_tokens = 0
    session_cost = 0.0

    while True:
        try:
            raw = await session.prompt_async(HTML("<ansigreen><b>você</b></ansigreen> > "))
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Até logo.[/dim]")
            break

        line = raw.strip()
        if not line:
            continue

        # Comandos especiais
        if line == "/exit":
            console.print("[dim]Até logo.[/dim]")
            break

        if line == "/clear":
            console.clear()
            console.print("[dim]Conversa limpa.[/dim]\n")
            continue

        if line == "/cost":
            _print_cost(session_input_tokens, session_output_tokens, session_cost)
            continue

        if line == "/tools":
            _print_tools(registry)
            continue

        if line.startswith("/"):
            console.print(f"[dim]Comandos: {', '.join(sorted(_COMMANDS))}[/dim]")
            continue

        # Executa o agente
        result = await _run_agent(line, registry, settings)
        session_input_tokens += result.total_input_tokens
        session_output_tokens += result.total_output_tokens
        session_cost += result.estimated_cost_usd

        _print_footer(result)
        console.print()


async def _run_agent(goal: str, registry: ToolRegistry, settings: object) -> AgentResult:
    from agent.config import get_settings as _gs

    cfg = _gs()
    planner = AnthropicTransport(model=cfg.anthropic.planner_model)
    reflector = AnthropicTransport(model=cfg.anthropic.reflector_model)

    agent = AIAgent(
        transport=planner,
        tool_registry=registry,
        reflector_transport=reflector,
    )

    console.print()
    prefix = Text("eve  > ", style="bold cyan")

    async def on_event(event: AgentEvent) -> None:
        match event.type:
            case "planner_text":
                console.print(prefix, event.data["text"], sep="")
                prefix.plain = "       "

            case "tool_call":
                name = event.data["name"]
                args = event.data.get("args", {})
                arg_str = ", ".join(f"{k}={escape(str(v))}" for k, v in args.items())
                console.print(f"       [yellow]🔧 {name}({arg_str})[/yellow]")

            case "tool_result":
                ok = event.data.get("ok", True)
                output = event.data.get("output")
                if ok and output is not None:
                    summary = _summarize_output(output)
                    console.print(f"       [dim]↳ {escape(summary)}[/dim]")
                elif not ok:
                    console.print("       [red]↳ erro[/red]")

            case "reflection":
                hint = event.data.get("ajuste_estrategia")
                if hint:
                    console.print(f"       [dim italic]💭 {escape(str(hint))}[/dim italic]")

    result = await agent.run(goal=goal, on_event=on_event)
    return result


def _summarize_output(output: object) -> str:
    if isinstance(output, list):
        return f"{len(output)} itens"
    if isinstance(output, dict):
        keys = list(output.keys())[:3]
        return "{" + ", ".join(keys) + ("..." if len(output) > 3 else "") + "}"
    text = str(output)
    return text[:120] + "..." if len(text) > 120 else text


def _print_footer(result: AgentResult) -> None:
    tokens = result.total_input_tokens + result.total_output_tokens
    cost = result.estimated_cost_usd
    duration = result.duration_s
    console.print(f"\n       [dim]─ {tokens:,} tokens · ${cost:.4f} · {duration:.1f}s ─[/dim]")


def _print_cost(in_tok: int, out_tok: int, cost: float) -> None:
    console.print(
        f"[dim]Sessão: {in_tok:,} in + {out_tok:,} out = "
        f"{in_tok + out_tok:,} tokens · ${cost:.4f}[/dim]"
    )


def _print_tools(registry: ToolRegistry) -> None:
    console.print("[bold]Tools disponíveis:[/bold]")
    for name in registry.names():
        tool = registry.get(name)
        if tool:
            lock = " [yellow]🔒[/yellow]" if tool.requires_confirmation else ""
            console.print(f"  [cyan]{name}[/cyan]{lock} — {tool.description}")
