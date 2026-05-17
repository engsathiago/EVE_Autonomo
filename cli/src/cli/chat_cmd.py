"""
agent chat — TUI interativo estilo OpenClaw.

Comando dedicado para abrir o REPL rico da EVE. Pode ser invocado como:
  agent chat
  eve              (se o entry-point estiver instalado)
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

app = typer.Typer()
console = Console()

_HISTORY_FILE = Path.home() / ".eve_chat_history"

_SLASH_COMMANDS = {
    "/help": "Lista todos os comandos",
    "/model": "Mostra ou troca o modelo (ex: /model ollama:gpt-oss:120b)",
    "/clear": "Limpa a tela",
    "/cost": "Total de custo desta sessão",
    "/tools": "Lista tools disponíveis",
    "/skills": "Lista skills carregadas",
    "/missions": "Lista missões ativas",
    "/approvals": "Lista aprovações pendentes",
    "/save": "Salva conversa atual em arquivo",
    "/reset": "Zera o histórico de tokens/custo desta sessão",
    "/exit": "Sai do chat (Ctrl+D também funciona)",
}


# ---------------------------------------------------------------------------
# Estado da sessão
# ---------------------------------------------------------------------------

class ChatState:
    def __init__(self, model: str):
        self.model = model
        self.messages = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self.started_at = time.time()
        self.transcript: list[tuple[str, str]] = []   # (role, content)

    def add_turn(self, user: str, assistant: str, in_tok: int, out_tok: int, cost: float):
        self.transcript.append(("user", user))
        self.transcript.append(("assistant", assistant))
        self.messages += 1
        self.total_input_tokens += in_tok
        self.total_output_tokens += out_tok
        self.total_cost_usd += cost

    def reset(self):
        self.messages = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self.transcript.clear()


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def chat(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override do modelo (ex: ollama:gpt-oss:120b)"),
) -> None:
    """Abre o chat interativo (TUI) com a EVE — estilo OpenClaw."""
    asyncio.run(_run_chat(model_override=model))


async def _run_chat(model_override: Optional[str] = None) -> None:
    from agent.config import get_settings
    from agent.observability import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)

    model = model_override or settings.models.default_model
    state = ChatState(model=model)

    _show_banner(state)

    # Inicializa registry de tools
    from agent.tools.registry import ToolRegistry, register_builtin
    registry = ToolRegistry()
    register_builtin(registry)

    # Prompt session com histórico e completion de slash commands
    style = Style.from_dict({
        "prompt": "ansigreen bold",
        "model": "ansicyan",
        "cost": "ansiyellow",
    })

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(_HISTORY_FILE)),
        completer=WordCompleter(list(_SLASH_COMMANDS.keys()), ignore_case=True),
        style=style,
        bottom_toolbar=lambda: _bottom_toolbar(state),
    )

    # Loop principal
    while True:
        try:
            raw = await session.prompt_async(
                HTML('<prompt>›</prompt> '),
            )
        except (EOFError, KeyboardInterrupt):
            console.print()
            console.print("[dim]Até logo! 👋[/dim]")
            break

        line = raw.strip()
        if not line:
            continue

        # Slash command?
        if line.startswith("/"):
            should_exit = await _handle_slash(line, state, registry, settings)
            if should_exit:
                break
            continue

        # Mensagem normal → executa o agente
        await _execute_turn(line, state, registry, settings)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _show_banner(state: ChatState) -> None:
    console.clear()
    console.print(Panel.fit(
        Text.from_markup(
            "[bold cyan]EVE[/bold cyan] — Agente Autônomo  "
            f"[dim]| modelo:[/dim] [cyan]{state.model}[/cyan]\n"
            "[dim]Digite[/dim] [yellow]/help[/yellow] [dim]para comandos · "
            "[yellow]/exit[/yellow] ou Ctrl+D para sair[/dim]"
        ),
        border_style="cyan",
    ))
    console.print()


def _bottom_toolbar(state: ChatState) -> HTML:
    elapsed = int(time.time() - state.started_at)
    mins, secs = divmod(elapsed, 60)
    return HTML(
        f' <model>{state.model}</model>  '
        f'│ msgs: {state.messages}  '
        f'│ tokens: {state.total_input_tokens + state.total_output_tokens:,}  '
        f'│ <cost>${state.total_cost_usd:.4f}</cost>  '
        f'│ ⏱ {mins:02d}:{secs:02d}'
    )


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

async def _handle_slash(line: str, state: ChatState, registry, settings) -> bool:
    """Retorna True se devemos sair do chat."""
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit", "/q"):
        console.print("[dim]Até logo! 👋[/dim]")
        return True

    elif cmd == "/help":
        _cmd_help()

    elif cmd == "/clear":
        _show_banner(state)

    elif cmd == "/model":
        if arg:
            _cmd_switch_model(state, arg.strip())
        else:
            console.print(f"[cyan]Modelo atual:[/cyan] {state.model}")
            console.print("[dim]Para trocar: /model ollama:gpt-oss:120b[/dim]")

    elif cmd == "/cost":
        _cmd_cost(state)

    elif cmd == "/tools":
        _cmd_tools(registry)

    elif cmd == "/skills":
        await _cmd_skills(settings)

    elif cmd == "/missions":
        await _cmd_missions(settings)

    elif cmd == "/approvals":
        await _cmd_approvals(settings)

    elif cmd == "/save":
        _cmd_save(state, arg)

    elif cmd == "/reset":
        state.reset()
        console.print("[green]✓[/green] Sessão zerada.")

    else:
        console.print(f"[red]Comando desconhecido:[/red] {cmd}")
        console.print(f"[dim]Use /help para ver comandos disponíveis[/dim]")

    return False


def _cmd_help() -> None:
    table = Table(show_header=False, border_style="cyan", title="Comandos disponíveis")
    table.add_column("Comando", style="cyan", width=20)
    table.add_column("Descrição", style="white")
    for cmd, desc in _SLASH_COMMANDS.items():
        table.add_row(cmd, desc)
    console.print(table)


def _cmd_switch_model(state: ChatState, new_model: str) -> None:
    if ":" not in new_model:
        console.print(f"[red]Formato inválido. Use provider:model_id[/red]")
        return

    old = state.model
    state.model = new_model
    console.print(f"[green]✓[/green] Modelo trocado: [dim]{old}[/dim] → [cyan]{new_model}[/cyan]")
    console.print("[dim](mudança vale para esta sessão; para persistir no .env use: agent config use <model>)[/dim]")


def _cmd_cost(state: ChatState) -> None:
    elapsed = int(time.time() - state.started_at)
    mins, secs = divmod(elapsed, 60)
    table = Table(show_header=False, border_style="yellow", title="Custo da Sessão")
    table.add_column("Métrica", style="yellow")
    table.add_column("Valor", style="white")
    table.add_row("Mensagens", str(state.messages))
    table.add_row("Tokens entrada", f"{state.total_input_tokens:,}")
    table.add_row("Tokens saída", f"{state.total_output_tokens:,}")
    table.add_row("Tokens total", f"{state.total_input_tokens + state.total_output_tokens:,}")
    table.add_row("Custo (USD)", f"${state.total_cost_usd:.4f}")
    table.add_row("Duração", f"{mins:02d}:{secs:02d}")
    console.print(table)


def _cmd_tools(registry) -> None:
    table = Table(show_header=True, border_style="magenta", title="Tools Disponíveis")
    table.add_column("Tool", style="cyan")
    table.add_column("Aprovação?", style="yellow")
    table.add_column("Descrição", style="dim")
    for name in registry.names():
        tool = registry.get(name)
        if tool:
            lock = "🔒 sim" if tool.requires_confirmation else "—"
            desc = (tool.description or "")[:60]
            table.add_row(name, lock, desc)
    console.print(table)


async def _cmd_skills(settings) -> None:
    try:
        from agent.skills.manager import SkillManager
        manager = await SkillManager.create_for_session(settings.skills)
        skills = manager.list_skills()
        if not skills:
            console.print("[dim]Nenhuma skill carregada.[/dim]")
            return

        table = Table(show_header=True, border_style="green", title=f"{len(skills)} Skills Ativas")
        table.add_column("Nome", style="cyan")
        table.add_column("Trigger", style="dim")
        table.add_column("Tools", style="yellow")
        for s in skills[:20]:
            tools_str = ", ".join(getattr(s, "tools", []) or [])
            trigger = (getattr(s, "trigger", "") or "")[:40]
            table.add_row(s.name, trigger, tools_str)
        console.print(table)
        if len(skills) > 20:
            console.print(f"[dim]... e mais {len(skills) - 20} skills[/dim]")
    except Exception as exc:
        console.print(f"[red]Erro carregando skills: {exc}[/red]")


async def _cmd_missions(settings) -> None:
    try:
        import asyncpg
        import os
        conn = await asyncpg.connect(os.environ.get("POSTGRES_URL", ""), timeout=3)
        try:
            rows = await conn.fetch(
                "SELECT id, goal, status, created_at FROM missions "
                "WHERE status IN ('active', 'paused') ORDER BY created_at DESC LIMIT 10"
            )
            if not rows:
                console.print("[dim]Nenhuma missão ativa.[/dim]")
                return

            table = Table(show_header=True, border_style="blue", title="Missões Ativas")
            table.add_column("ID", style="cyan", width=12)
            table.add_column("Status", style="yellow")
            table.add_column("Objetivo", style="white")
            for r in rows:
                mid = str(r["id"])[:10]
                table.add_row(mid, r["status"], (r["goal"] or "")[:70])
            console.print(table)
        finally:
            await conn.close()
    except Exception as exc:
        console.print(f"[dim]Não foi possível listar missões: {exc}[/dim]")


async def _cmd_approvals(settings) -> None:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://localhost:8000/v1/approvals")
            if r.status_code != 200:
                console.print(f"[red]Core retornou HTTP {r.status_code}[/red]")
                return
            approvals = r.json().get("approvals", [])
            if not approvals:
                console.print("[dim]Nenhuma aprovação pendente.[/dim]")
                return
            table = Table(show_header=True, border_style="red", title="Aprovações Pendentes")
            table.add_column("ID", style="cyan", width=10)
            table.add_column("Ação", style="yellow")
            table.add_column("Detalhes", style="dim")
            for a in approvals:
                aid = str(a.get("id", ""))[:8]
                action = a.get("action", "")
                params = str(a.get("params", {}))[:60]
                table.add_row(aid, action, params)
            console.print(table)
    except Exception as exc:
        console.print(f"[dim]Core não acessível: {exc}[/dim]")


def _cmd_save(state: ChatState, arg: str) -> None:
    if not state.transcript:
        console.print("[dim]Nada para salvar.[/dim]")
        return

    path = Path(arg) if arg else Path(f"eve-chat-{int(time.time())}.md")
    lines = [
        f"# Conversa com EVE",
        f"",
        f"- **Modelo:** {state.model}",
        f"- **Mensagens:** {state.messages}",
        f"- **Tokens:** {state.total_input_tokens + state.total_output_tokens:,}",
        f"- **Custo:** ${state.total_cost_usd:.4f}",
        f"",
        "---",
        "",
    ]
    for role, content in state.transcript:
        prefix = "**Você**" if role == "user" else "**EVE**"
        lines.append(f"{prefix}: {content}\n")

    path.write_text("\n".join(lines))
    console.print(f"[green]✓[/green] Conversa salva em [cyan]{path.resolve()}[/cyan]")


# ---------------------------------------------------------------------------
# Execução de um turno
# ---------------------------------------------------------------------------

async def _execute_turn(user_input: str, state: ChatState, registry, settings) -> None:
    """Executa uma mensagem do usuário e mostra a resposta da EVE."""
    from agent.core import AIAgent
    from agent.events import AgentEvent
    from agent.transports import AnthropicTransport

    # Provider/model dinâmico — respeita troca via /model
    planner = _build_transport_for_model(state.model, settings)
    reflector = AnthropicTransport(model=settings.anthropic.reflector_model) \
        if settings.anthropic.api_key else planner

    agent = AIAgent(
        transport=planner,
        tool_registry=registry,
        reflector_transport=reflector,
    )

    console.print()
    response_text = ""

    async def on_event(event: AgentEvent) -> None:
        nonlocal response_text
        match event.type:
            case "planner_text":
                text = event.data.get("text", "")
                if text:
                    # Renderiza como Markdown se parece conter formatação
                    if any(m in text for m in ("```", "**", "##", "- ")):
                        console.print(Panel(
                            Markdown(text),
                            title="[bold cyan]EVE[/bold cyan]",
                            border_style="cyan",
                            padding=(0, 1),
                        ))
                    else:
                        console.print(f"[bold cyan]EVE[/bold cyan]  {text}")
                    response_text += text

            case "tool_call":
                name = event.data["name"]
                args = event.data.get("args", {})
                arg_str = ", ".join(f"{k}={escape(str(v))[:30]}" for k, v in args.items())
                console.print(f"  [yellow]🔧 {name}([dim]{arg_str}[/dim])[/yellow]")

            case "tool_result":
                ok = event.data.get("ok", True)
                if ok:
                    output = event.data.get("output")
                    summary = _summarize_output(output)
                    console.print(f"     [dim]↳ {escape(summary)}[/dim]")
                else:
                    err = event.data.get("error", "")
                    console.print(f"     [red]✗ {escape(str(err))[:80]}[/red]")

            case "reflection":
                hint = event.data.get("ajuste_estrategia")
                if hint:
                    console.print(f"     [italic dim]💭 {escape(str(hint))[:120]}[/italic dim]")

    try:
        result = await agent.run(
            goal=user_input,
            on_event=on_event,
            model_override=state.model,
        )

        state.add_turn(
            user=user_input,
            assistant=response_text or result.final_text,
            in_tok=result.total_input_tokens,
            out_tok=result.total_output_tokens,
            cost=result.estimated_cost_usd,
        )

        # Footer
        console.print(
            f"\n  [dim]─ {result.iterations} iter · "
            f"{result.total_input_tokens + result.total_output_tokens:,} tokens · "
            f"${result.estimated_cost_usd:.4f} · {result.duration_s:.1f}s ─[/dim]\n"
        )
    except Exception as exc:
        console.print(f"\n[red]Erro:[/red] {escape(str(exc))}\n")


def _build_transport_for_model(model: str, settings):
    """Cria um transport baseado no provider:model_id."""
    from agent.transports import AnthropicTransport

    provider = model.split(":")[0] if ":" in model else "anthropic"

    if provider == "ollama":
        from agent.models.transports.ollama import OllamaTransport
        # Para Ollama, o "modelo" inclui o provider; passamos só o nome do modelo
        # mas o AIAgent vai usar o model_override
        return OllamaTransport(
            base_url=settings.ollama.base_url,
            api_key=settings.ollama.api_key,
        )

    # Fallback para Anthropic (transport legacy usado pelo AIAgent)
    return AnthropicTransport(model=settings.anthropic.planner_model)


def _summarize_output(output) -> str:
    if isinstance(output, list):
        return f"{len(output)} itens"
    if isinstance(output, dict):
        keys = list(output.keys())[:3]
        return "{" + ", ".join(keys) + ("..." if len(output) > 3 else "") + "}"
    text = str(output)
    return text[:120] + "..." if len(text) > 120 else text
