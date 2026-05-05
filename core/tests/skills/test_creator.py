"""Testes do SkillCreator — Milestone E."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.skills.creator import SkillCreator
from agent.skills.schema import SkillManifest, SkillResult
from agent.transports.base import ChatResponse

EXTRACT_SKILL_MANIFEST = SkillManifest(
    name="extract_skill",
    description="Meta-skill para extrair skills de sessões",
    prompt="Analise: {{ session_log }}\nTarefa: {{ task_description }}",
    content_hash="abc",
)

VALID_DRAFT_CONTENT = """\
---
name: my_extracted_skill
version: 1
description: Skill extraída automaticamente para resumir texto.
arguments:
  - name: text
    type: string
    required: true
tools: []
tags: [text, auto]
---

Você é um resumidor. Resuma: {{ text }}
"""


def _make_creator(
    drafts_dir: Path,
    llm_output: str = VALID_DRAFT_CONTENT,
    messages: list | None = None,
) -> SkillCreator:
    transport = MagicMock()
    transport.chat = AsyncMock(
        return_value=ChatResponse(
            text=llm_output,
            tool_calls=[],
            raw={},
            usage={"input_tokens": 50, "output_tokens": 200},
        )
    )

    memory_store = MagicMock()
    memory_store.get_messages = AsyncMock(
        return_value=messages or [
            {"role": "user", "content": "Resuma este artigo"},
            {"role": "assistant", "content": "Aqui está o resumo: ..."},
            {"role": "user", "content": "Perfeito, obrigado!"},
        ]
    )

    manager = MagicMock()
    manager.get = MagicMock(return_value=EXTRACT_SKILL_MANIFEST)

    return SkillCreator(
        manager=manager,
        transport=transport,
        memory_store=memory_store,
        drafts_dir=drafts_dir,
    )


class TestExtractFromSession:
    async def test_creates_draft_on_success(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        creator = _make_creator(drafts_dir)
        path = await creator.extract_from_session(uuid4(), "resumiu texto com sucesso")

        assert path is not None
        assert path.exists()
        assert path.name == "my_extracted_skill.md"
        assert path.read_text().startswith("---")

    async def test_returns_none_when_session_too_short(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        creator = _make_creator(drafts_dir, messages=[{"role": "user", "content": "oi"}])
        result = await creator.extract_from_session(uuid4())
        assert result is None
        assert not drafts_dir.exists()

    async def test_returns_none_when_llm_says_no_skill(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        creator = _make_creator(drafts_dir, llm_output="NO_SKILL")
        result = await creator.extract_from_session(uuid4())
        assert result is None

    async def test_returns_none_on_llm_failure(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        creator = _make_creator(drafts_dir)
        creator._transport.chat = AsyncMock(side_effect=RuntimeError("API down"))
        result = await creator.extract_from_session(uuid4())
        assert result is None

    async def test_returns_none_when_draft_has_no_name(self, tmp_path: Path) -> None:
        bad_content = "---\ndescription: sem nome\n---\nprompt"
        creator = _make_creator(tmp_path / "_drafts", llm_output=bad_content)
        result = await creator.extract_from_session(uuid4())
        assert result is None

    async def test_draft_content_is_valid_frontmatter(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        creator = _make_creator(drafts_dir)
        path = await creator.extract_from_session(uuid4())

        import frontmatter as fm
        post = fm.loads(path.read_text())
        assert post.metadata["name"] == "my_extracted_skill"
        assert "description" in post.metadata


class TestListDrafts:
    def test_returns_empty_when_no_drafts_dir(self, tmp_path: Path) -> None:
        creator = _make_creator(tmp_path / "_drafts")
        assert creator.list_drafts() == []

    async def test_lists_created_drafts(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        creator = _make_creator(drafts_dir)
        await creator.extract_from_session(uuid4())
        drafts = creator.list_drafts()
        assert len(drafts) == 1
        assert drafts[0].suffix == ".md"


class TestPromote:
    def _setup(self, tmp_path: Path) -> tuple[SkillCreator, Path]:
        drafts_dir = tmp_path / "_drafts"
        drafts_dir.mkdir()
        draft = drafts_dir / "my_extracted_skill.md"
        draft.write_text(VALID_DRAFT_CONTENT, encoding="utf-8")
        creator = _make_creator(drafts_dir)
        return creator, draft

    def test_moves_draft_to_skills_dir(self, tmp_path: Path) -> None:
        creator, draft = self._setup(tmp_path)
        target = creator.promote(draft)
        assert target.exists()
        assert target.parent == tmp_path  # parent do _drafts
        assert not draft.exists()  # removido de _drafts

    def test_missing_draft_raises(self, tmp_path: Path) -> None:
        creator = _make_creator(tmp_path / "_drafts")
        with pytest.raises(FileNotFoundError):
            creator.promote(tmp_path / "nonexistent.md")

    def test_promote_no_name_raises(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        drafts_dir.mkdir()
        bad = drafts_dir / "bad.md"
        bad.write_text("---\ndescription: sem nome\n---\np")
        creator = _make_creator(drafts_dir)
        with pytest.raises(ValueError, match="name"):
            creator.promote(bad)

    def test_cannot_promote_over_builtin(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        drafts_dir.mkdir()
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        (builtin_dir / "summarize_text.md").write_text("builtin")

        draft = drafts_dir / "summarize_text.md"
        draft.write_text("---\nname: summarize_text\ndescription: d\n---\np")
        creator = _make_creator(drafts_dir)
        with pytest.raises(PermissionError, match="builtin"):
            creator.promote(draft)


class TestDiscard:
    def test_removes_draft(self, tmp_path: Path) -> None:
        drafts_dir = tmp_path / "_drafts"
        drafts_dir.mkdir()
        draft = drafts_dir / "test.md"
        draft.write_text("content")
        creator = _make_creator(drafts_dir)
        creator.discard(draft)
        assert not draft.exists()

    def test_missing_raises(self, tmp_path: Path) -> None:
        creator = _make_creator(tmp_path / "_drafts")
        with pytest.raises(FileNotFoundError):
            creator.discard(tmp_path / "ghost.md")
