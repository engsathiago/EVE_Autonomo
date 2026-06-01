"""
Lê skills de disco (.md com frontmatter ou pasta com manifest.yaml + prompt.md).
Calcula hash do conteúdo para detectar mudanças sem re-embedar desnecessariamente.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import frontmatter  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

from agent.observability.logger import get_logger
from agent.skills.schema import SkillArgument, SkillManifest

log = get_logger(__name__)

_ALLOWED_TOOL_IMPORT_PREFIXES = ("agent.tools", "agent.skills")


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _parse_argument(raw: dict[str, Any]) -> SkillArgument:
    return SkillArgument(
        name=raw["name"],
        type=raw.get("type", "string"),
        required=raw.get("required", False),
        default=raw.get("default"),
        values=raw.get("values"),
        description=raw.get("description"),
    )


def _build_manifest(meta: dict[str, Any], prompt: str, source_path: str) -> SkillManifest:
    if "name" not in meta:
        raise ValueError(f"Skill em '{source_path}' não tem campo 'name'.")
    if "description" not in meta:
        raise ValueError(f"Skill '{meta['name']}' não tem campo 'description'.")

    raw_args: list[dict[str, Any]] = meta.get("arguments", [])
    arguments = [_parse_argument(a) for a in raw_args]

    combined = f"{meta}\n{prompt}"
    return SkillManifest(
        name=meta["name"],
        version=int(meta.get("version", 1)),
        description=meta["description"],
        arguments=arguments,
        tools=meta.get("tools", []),
        tags=meta.get("tags", []),
        requires_approval=bool(meta.get("requires_approval", False)),
        prompt=prompt,
        source_path=source_path,
        content_hash=_hash(combined),
    )


def load_from_file(path: Path) -> SkillManifest:
    """Carrega skill de um arquivo .md com frontmatter YAML."""
    text = path.read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    meta: dict[str, Any] = dict(post.metadata)
    prompt: str = post.content.strip()
    return _build_manifest(meta, prompt, str(path))


def load_from_dir(path: Path) -> SkillManifest:
    """Carrega skill de pasta: manifest.yaml + prompt.md obrigatórios."""
    manifest_path = path / "manifest.yaml"
    prompt_path = path / "prompt.md"

    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.yaml não encontrado em '{path}'.")
    if not prompt_path.exists():
        raise FileNotFoundError(f"prompt.md não encontrado em '{path}'.")

    meta: dict[str, Any] = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    prompt = prompt_path.read_text(encoding="utf-8").strip()

    tools_py = path / "tools.py"
    if tools_py.exists():
        _validate_tools_py(tools_py)

    return _build_manifest(meta, prompt, str(path))


def _validate_tools_py(path: Path) -> None:
    """Garante que tools.py só importa de prefixos permitidos."""
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("import ", "from ")):
            continue
        # Extrai o módulo importado
        module = stripped.split()[1].split(".")[0]
        if not any(
            stripped.startswith(f"from {p}") or stripped.startswith(f"import {p}")
            for p in _ALLOWED_TOOL_IMPORT_PREFIXES
        ):
            # Bibliotecas padrão e comuns são permitidas
            _STDLIB_OR_ALLOWED = {
                "typing",
                "pathlib",
                "os",
                "sys",
                "re",
                "json",
                "datetime",
                "collections",
                "functools",
                "itertools",
                "asyncio",
                "abc",
                "uuid",
                "hashlib",
                "pydantic",
                "httpx",
                "anyio",
            }
            if module not in _STDLIB_OR_ALLOWED:
                raise PermissionError(
                    f"tools.py em '{path.parent}' importa módulo não permitido: '{module}'. "
                    f"Permitidos: {_ALLOWED_TOOL_IMPORT_PREFIXES} + stdlib."
                )


def load_all_from_dir(skills_dir: Path) -> list[SkillManifest]:
    """
    Varre skills_dir recursivamente.
    - Arquivos .md (exceto _drafts/) → load_from_file
    - Subpastas com manifest.yaml → load_from_dir
    Levanta ValueError em nome duplicado.
    """
    skills: list[SkillManifest] = []
    seen_names: dict[str, str] = {}
    drafts_dir = skills_dir / "_drafts"

    for item in sorted(skills_dir.rglob("*")):
        # Ignora _drafts e arquivos ocultos
        if drafts_dir in item.parents or item.name.startswith("."):
            continue

        try:
            if item.is_file() and item.suffix == ".md":
                skill = load_from_file(item)
            elif item.is_dir() and (item / "manifest.yaml").exists():
                skill = load_from_dir(item)
            else:
                continue
        except Exception as exc:
            log.warning("skill.load.failed", path=str(item), error=str(exc))
            continue

        if skill.name in seen_names:
            raise ValueError(
                f"Nome de skill duplicado: '{skill.name}' ('{seen_names[skill.name]}' e '{skill.source_path}')."
            )
        seen_names[skill.name] = skill.source_path
        skills.append(skill)
        log.debug("skill.loaded", name=skill.name, version=skill.version)

    return skills
