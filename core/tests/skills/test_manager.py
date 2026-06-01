"""Testes do SkillManager — Milestone B."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.skills.manager import SkillManager, _cosine
from agent.skills.schema import SkillManifest, SkillNotFound

BUILTIN_DIR = Path(__file__).parents[2] / "src" / "agent" / "skills"


def _make_manifest(name: str, description: str, tags: list[str] | None = None) -> SkillManifest:
    return SkillManifest(
        name=name,
        description=description,
        tags=tags or [],
        content_hash="abc123",
    )


def _fake_embed(text: str) -> list[float]:
    """Embedding determinístico simples para testes: hash do texto → vetor normalizado."""
    import hashlib
    import math

    seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
    raw = [(seed * (i + 1)) % 997 / 997.0 for i in range(8)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


@pytest.fixture
def mock_transport() -> MagicMock:
    return MagicMock()


@pytest.fixture
def manager(tmp_path: Path, mock_transport: MagicMock) -> SkillManager:
    return SkillManager(skills_dir=tmp_path, transport=mock_transport)


@pytest.fixture
def populated_manager(manager: SkillManager) -> SkillManager:
    """Manager com 3 skills pré-carregadas sem embedder real."""
    skills = [
        _make_manifest("summarize_text", "Resume um texto em bullets ou parágrafos", ["text", "productivity"]),
        _make_manifest("web_research", "Pesquisa na web e retorna resumo com fontes", ["web", "research"]),
        _make_manifest("file_inspect", "Lê e analisa arquivos locais", ["files", "code"]),
    ]
    for skill in skills:
        vec = _fake_embed(skill.description)
        manager._registry.add(skill, vec)
    return manager


class TestCosine:
    def test_identical_vectors(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_zero_vector(self) -> None:
        assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


class TestManagerList:
    def test_list_all(self, populated_manager: SkillManager) -> None:
        skills = populated_manager.list()
        assert len(skills) == 3

    def test_list_by_tag(self, populated_manager: SkillManager) -> None:
        skills = populated_manager.list(tag="web")
        assert len(skills) == 1
        assert skills[0].name == "web_research"

    def test_list_missing_tag_returns_empty(self, populated_manager: SkillManager) -> None:
        assert populated_manager.list(tag="nonexistent") == []


class TestManagerGet:
    def test_get_existing(self, populated_manager: SkillManager) -> None:
        m = populated_manager.get("summarize_text")
        assert m.name == "summarize_text"

    def test_get_missing_raises(self, populated_manager: SkillManager) -> None:
        with pytest.raises(SkillNotFound, match="missing_skill"):
            populated_manager.get("missing_skill")

    def test_has_existing(self, populated_manager: SkillManager) -> None:
        assert populated_manager.has("web_research") is True

    def test_has_missing(self, populated_manager: SkillManager) -> None:
        assert populated_manager.has("nope") is False


class TestManagerMatch:
    async def test_match_returns_top_k(self, populated_manager: SkillManager) -> None:
        with patch("agent.skills.manager.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _fake_embed("resumir documento")
            results = await populated_manager.match("resumir documento", k=2)
        assert len(results) <= 2
        assert all(0.0 <= r.score <= 1.0 for r in results)

    async def test_match_sorted_descending(self, populated_manager: SkillManager) -> None:
        with patch("agent.skills.manager.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _fake_embed("pesquisar na internet")
            results = await populated_manager.match("pesquisar na internet", k=3)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_name_boost_for_exact_match(self, populated_manager: SkillManager) -> None:
        """Skill cujo nome está na query deve ter score >= skill sem nome."""
        with patch("agent.skills.manager.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _fake_embed("web_research sobre python")
            results = await populated_manager.match("web_research sobre python", k=3)
        names = [r.manifest.name for r in results]
        # web_research deve aparecer primeiro (boost por nome exato)
        assert names[0] == "web_research"

    async def test_match_with_tag_filter(self, populated_manager: SkillManager) -> None:
        with patch("agent.skills.manager.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _fake_embed("algo")
            results = await populated_manager.match("algo", k=3, must_have_tag="files")
        assert all("files" in r.manifest.tags for r in results)
        assert len(results) == 1

    async def test_match_empty_registry(self, manager: SkillManager) -> None:
        with patch("agent.skills.manager.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _fake_embed("qualquer coisa")
            results = await manager.match("qualquer coisa")
        assert results == []

    async def test_performance_50_skills(self, mock_transport: MagicMock) -> None:
        """Match em 50 skills deve completar em < 100ms (excluindo cold start do embedder)."""
        tmp = Path("/tmp/perf_skills_test")
        big_manager = SkillManager(skills_dir=tmp, transport=mock_transport)

        for i in range(50):
            m = _make_manifest(f"skill_{i}", f"Skill número {i} que faz alguma coisa específica")
            big_manager._registry.add(m, _fake_embed(m.description))

        query_vec = _fake_embed("executar tarefa")
        with patch("agent.skills.manager.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = query_vec
            start = time.monotonic()
            results = await big_manager.match("executar tarefa", k=3)
            elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 100, f"match demorou {elapsed_ms:.1f}ms — excede 100ms"
        assert len(results) == 3


class TestToToolSchema:
    def test_generates_anthropic_schema(self, manager: SkillManager) -> None:
        manifest = _make_manifest("my_skill", "Faz algo")
        manifest.arguments = []
        schema = manager.to_tool_schema(manifest)
        assert schema["name"] == "skill__my_skill"
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_required_args_in_schema(self, manager: SkillManager) -> None:
        from agent.skills.schema import SkillArgument

        manifest = _make_manifest("my_skill", "d")
        manifest.arguments = [
            SkillArgument(name="text", type="string", required=True),
            SkillArgument(name="count", type="integer", required=False, default=5),
        ]
        schema = manager.to_tool_schema(manifest)
        assert "text" in schema["input_schema"]["required"]
        assert "count" not in schema["input_schema"]["required"]
        assert schema["input_schema"]["properties"]["count"]["type"] == "integer"

    def test_enum_arg(self, manager: SkillManager) -> None:
        from agent.skills.schema import SkillArgument

        manifest = _make_manifest("my_skill", "d")
        manifest.arguments = [
            SkillArgument(name="mode", type="enum", values=["a", "b"], default="a"),
        ]
        schema = manager.to_tool_schema(manifest)
        assert schema["input_schema"]["properties"]["mode"]["enum"] == ["a", "b"]
