"""
SkillCreator: extrai skills reutilizáveis de sessões bem-sucedidas.
Drafts ficam em _drafts/ e requerem aprovação manual via CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import frontmatter  # type: ignore[import-untyped]

from agent.observability.logger import get_logger
from agent.skills.schema import SkillError

if TYPE_CHECKING:
    from agent.memory.store import MemoryStore
    from agent.skills.manager import SkillManager
    from agent.transports.base import BaseTransport

log = get_logger(__name__)

_NO_SKILL_SENTINEL = "NO_SKILL"


class SkillCreator:
    def __init__(
        self,
        manager: SkillManager,
        transport: BaseTransport,
        memory_store: MemoryStore,
        drafts_dir: Path,
    ) -> None:
        self._manager = manager
        self._transport = transport
        self._memory_store = memory_store
        self._drafts_dir = drafts_dir

    async def extract_from_session(
        self,
        session_id: UUID,
        task_description: str | None = None,
    ) -> Path | None:
        """
        Lê o histórico da sessão, chama o LLM com a meta-skill extract_skill,
        salva o draft em _drafts/. Retorna o path do draft ou None se não
        havia conteúdo extraível.
        """
        messages = await self._memory_store.get_messages(session_id, limit=100)
        if len(messages) < 2:
            log.info("skill.creator.skip", reason="sessão muito curta", session_id=str(session_id))
            return None

        session_log = json.dumps(
            [{"role": m["role"], "content": str(m["content"])[:500]} for m in messages],
            ensure_ascii=False,
        )
        description = task_description or f"sessão {session_id}"

        extract_skill = self._manager.get("extract_skill")
        from agent.skills.template_runner import TemplateSkillRunner as SkillRunner

        runner = SkillRunner(transport=self._transport)

        try:
            result = await runner.execute(
                extract_skill,
                {"session_log": session_log, "task_description": description},
            )
        except SkillError as exc:
            log.warning("skill.creator.llm_failed", error=str(exc))
            return None

        raw_output = str(result.output or "").strip()
        if not raw_output or raw_output == _NO_SKILL_SENTINEL:
            log.info("skill.creator.no_skill", session_id=str(session_id))
            return None

        return self._save_draft(raw_output, session_id)

    def _save_draft(self, content: str, session_id: UUID) -> Path | None:
        """Valida o frontmatter do draft e salva em _drafts/."""
        try:
            post = frontmatter.loads(content)
            name = post.metadata.get("name")
            if not name:
                log.warning("skill.creator.draft_no_name", session_id=str(session_id))
                return None
        except Exception as exc:
            log.warning("skill.creator.draft_parse_failed", error=str(exc))
            return None

        self._drafts_dir.mkdir(parents=True, exist_ok=True)
        draft_path = self._drafts_dir / f"{name}.md"
        draft_path.write_text(content, encoding="utf-8")
        log.info("skill.creator.draft_saved", path=str(draft_path), name=name)
        return draft_path

    def list_drafts(self) -> list[Path]:
        if not self._drafts_dir.exists():
            return []
        return sorted(self._drafts_dir.glob("*.md"))

    def promote(self, draft_path: Path) -> Path:
        """
        Valida o draft, move para o diretório de skills ativo.
        Não sobrescreve skills builtin.
        """
        if not draft_path.exists():
            raise FileNotFoundError(f"Draft não encontrado: '{draft_path}'")

        post = frontmatter.loads(draft_path.read_text(encoding="utf-8"))
        name = post.metadata.get("name")
        if not name:
            raise ValueError(f"Draft '{draft_path.name}' não tem campo 'name' no frontmatter.")

        # Destino: diretório de skills (parent do _drafts)
        skills_dir = self._drafts_dir.parent
        target = skills_dir / f"{name}.md"

        # Não deixa sobrescrever builtins
        builtin_dir = skills_dir / "builtin"
        if (builtin_dir / f"{name}.md").exists():
            raise PermissionError(
                f"Skill '{name}' é builtin e não pode ser sobrescrita via promote."
            )

        draft_path.rename(target)
        log.info("skill.creator.promoted", name=name, target=str(target))
        return target

    def discard(self, draft_path: Path) -> None:
        if not draft_path.exists():
            raise FileNotFoundError(f"Draft não encontrado: '{draft_path}'")
        draft_path.unlink()
        log.info("skill.creator.discarded", path=str(draft_path))
