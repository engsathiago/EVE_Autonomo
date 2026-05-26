"""
Comandos CLI para o sistema de skills: list, show, run, review, create-from-session, validate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(name="skill", help="Gerenciar e executar skills do agente.")
console = Console()


def _get_skills_dir() -> Path:
    from agent.config import get_settings

    return Path(get_settings().skills.skills_dir)


def _get_drafts_dir() -> Path:
    from agent.config import get_settings

    return Path(get_settings().skills.skills_drafts_dir)


def _build_manager_sync() -> SkillManager:  # type: ignore[name-defined]  # noqa: F821
    from agent.config import get_settings
    from agent.skills.manager import SkillManager
    from agent.transports.anthropic import AnthropicTransport

    settings = get_settings()
    transport = AnthropicTransport(
        model=settings.anthropic.planner_model,
    )
    manager = SkillManager(
        skills_dir=_get_skills_dir(),
        transport=transport,
        cache_dir=Path(settings.skills.skills_embedding_cache_dir),
    )
    return manager


@app.command("list")
def skill_list(
    tag: Annotated[str | None, typer.Option("--tag", "-t", help="Filtrar por tag")] = None,
) -> None:
    """Lista todas as skills disponíveis."""
    from agent.skills.loader import load_all_from_dir

    try:
        skills = load_all_from_dir(_get_skills_dir())
    except Exception as exc:
        console.print(f"[red]Erro ao carregar skills: {exc}[/red]")
        raise typer.Exit(1)

    if tag:
        skills = [s for s in skills if tag in s.tags]

    if not skills:
        console.print("[yellow]Nenhuma skill encontrada.[/yellow]")
        return

    table = Table(title="Skills disponíveis", show_lines=False)
    table.add_column("Nome", style="cyan", no_wrap=True)
    table.add_column("v", style="dim", width=3)
    table.add_column("Tags", style="green")
    table.add_column("Aprovação", style="yellow", width=10)
    table.add_column("Descrição")

    for s in sorted(skills, key=lambda x: x.name):
        approval = "✓" if s.requires_approval else ""
        table.add_row(
            s.name,
            str(s.version),
            ", ".join(s.tags),
            approval,
            s.description[:80],
        )

    console.print(table)
    console.print(f"[dim]Total: {len(skills)} skill(s)[/dim]")


@app.command("show")
def skill_show(name: str) -> None:
    """Exibe manifest e prompt de uma skill."""
    from agent.skills.loader import load_all_from_dir

    skills = {s.name: s for s in load_all_from_dir(_get_skills_dir())}
    skill = skills.get(name)
    if not skill:
        console.print(f"[red]Skill '{name}' não encontrada.[/red]")
        raise typer.Exit(1)

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Campo", style="bold cyan", width=14)
    table.add_column("Valor")
    table.add_row("Nome", skill.name)
    table.add_row("Versão", str(skill.version))
    table.add_row("Tags", ", ".join(skill.tags))
    table.add_row("Aprovação", str(skill.requires_approval))
    table.add_row("Tools", ", ".join(skill.tools) or "—")

    if skill.arguments:
        args_str = "\n".join(
            f"  {a.name}: {a.type}{'*' if a.required else ''}"
            + (f" = {a.default}" if a.default is not None else "")
            for a in skill.arguments
        )
        table.add_row("Argumentos", args_str)

    console.print(Panel(table, title=f"[bold]{skill.name}[/bold]", subtitle=skill.description))
    console.print(Panel(skill.prompt, title="Prompt", border_style="dim"))


@app.command("run")
def skill_run(
    name: str,
    arg: Annotated[
        list[str],
        typer.Option("--arg", "-a", help="Argumento no formato nome=valor"),
    ] = [],
) -> None:
    """Executa uma skill standalone (útil para debug)."""
    arguments: dict[str, str] = {}
    for a in arg:
        if "=" not in a:
            console.print(f"[red]Argumento inválido '{a}' — use nome=valor.[/red]")
            raise typer.Exit(1)
        k, _, v = a.partition("=")
        arguments[k.strip()] = v.strip()

    async def _run() -> None:
        manager = _build_manager_sync()
        await manager.load_all()
        try:
            result = await manager.run(name, arguments)
            console.print(Panel(str(result.output), title=f"[green]Resultado: {name}[/green]"))
            console.print(f"[dim]Latência: {result.latency_ms}ms[/dim]")
        except Exception as exc:
            console.print(f"[red]Erro: {exc}[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())


@app.command("validate")
def skill_validate(path: str) -> None:
    """Valida a sintaxe de um arquivo de skill."""
    from agent.skills.loader import load_from_dir, load_from_file

    p = Path(path)
    try:
        if p.is_dir():
            skill = load_from_dir(p)
        else:
            skill = load_from_file(p)
        console.print(f"[green]✓[/green] Skill '{skill.name}' válida (v{skill.version})")
        console.print(f"  [dim]Hash: {skill.content_hash}[/dim]")
    except Exception as exc:
        console.print(f"[red]✗ Inválida: {exc}[/red]")
        raise typer.Exit(1)


@app.command("review")
def skill_review(
    promote: Annotated[
        str | None, typer.Option("--promote", help="Promover draft pelo nome")
    ] = None,
    discard: Annotated[
        str | None, typer.Option("--discard", help="Descartar draft pelo nome")
    ] = None,
) -> None:
    """Lista, promove ou descarta drafts de skills auto-criadas."""
    from agent.skills.creator import SkillCreator

    drafts_dir = _get_drafts_dir()
    creator = SkillCreator(
        manager=None,  # type: ignore[arg-type]
        transport=None,  # type: ignore[arg-type]
        memory_store=None,  # type: ignore[arg-type]
        drafts_dir=drafts_dir,
    )

    if promote:
        draft_path = drafts_dir / f"{promote}.md"
        try:
            target = creator.promote(draft_path)
            console.print(f"[green]✓[/green] Draft '{promote}' promovido para {target}")
        except Exception as exc:
            console.print(f"[red]Erro: {exc}[/red]")
            raise typer.Exit(1)
        return

    if discard:
        draft_path = drafts_dir / f"{discard}.md"
        try:
            creator.discard(draft_path)
            console.print(f"[yellow]Draft '{discard}' descartado.[/yellow]")
        except Exception as exc:
            console.print(f"[red]Erro: {exc}[/red]")
            raise typer.Exit(1)
        return

    # Listar drafts
    drafts = creator.list_drafts()
    if not drafts:
        console.print("[dim]Nenhum draft pendente em[/dim] " + str(drafts_dir))
        return

    table = Table(title="Drafts pendentes de aprovação")
    table.add_column("Nome", style="cyan")
    table.add_column("Tamanho", justify="right")

    for d in drafts:
        table.add_row(d.stem, f"{d.stat().st_size} bytes")

    console.print(table)
    console.print(
        "[dim]Use [bold]agent skill review --promote NOME[/bold] para aprovar ou "
        "[bold]--discard NOME[/bold] para descartar.[/dim]"
    )


@app.command("create-from-session")
def skill_create_from_session(
    session_id: str,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Descrição do que a sessão completou"),
    ] = None,
) -> None:
    """Extrai uma skill de uma sessão bem-sucedida (requer banco de dados)."""
    try:
        sid = UUID(session_id)
    except ValueError:
        console.print(f"[red]session_id inválido: '{session_id}'[/red]")
        raise typer.Exit(1)

    async def _run() -> None:
        from agent.config import get_settings
        from agent.memory.store import MemoryStore
        from agent.skills.creator import SkillCreator

        settings = get_settings()
        from agent.transports.anthropic import AnthropicTransport

        transport = AnthropicTransport(
            model=settings.anthropic.planner_model,
        )
        manager = _build_manager_sync()
        await manager.load_all()

        memory_store = await MemoryStore.create()

        creator = SkillCreator(
            manager=manager,
            transport=transport,
            memory_store=memory_store,
            drafts_dir=_get_drafts_dir(),
        )
        try:
            path = await creator.extract_from_session(sid, description)
            if path:
                console.print(f"[green]✓[/green] Draft criado: {path}")
                console.print(
                    f"[dim]Revisar com:[/dim] [bold]agent skill review --promote {path.stem}[/bold]"
                )
            else:
                console.print("[yellow]Nenhuma skill extraível nesta sessão.[/yellow]")
        finally:
            await memory_store.close()

    asyncio.run(_run())
