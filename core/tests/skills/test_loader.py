"""Testes do SkillLoader — Milestone A."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.skills.loader import load_all_from_dir, load_from_dir, load_from_file

FIXTURES = Path(__file__).parent / "fixtures"
BUILTIN = Path(__file__).parents[2] / "src" / "agent" / "skills" / "builtin"


class TestLoadFromFile:
    def test_parses_valid_md(self) -> None:
        skill = load_from_file(FIXTURES / "good_skill.md")
        assert skill.name == "good_skill"
        assert skill.version == 2
        assert "Uma skill de teste" in skill.description
        assert len(skill.arguments) == 2
        assert skill.arguments[0].name == "input_text"
        assert skill.arguments[0].required is True
        assert skill.arguments[1].type == "enum"
        assert skill.arguments[1].values == ["fast", "slow"]
        assert "fixture" in skill.tags
        assert skill.prompt != ""
        assert skill.content_hash != ""

    def test_source_path_is_set(self) -> None:
        skill = load_from_file(FIXTURES / "good_skill.md")
        assert "good_skill.md" in skill.source_path

    def test_missing_name_raises(self, tmp_path: Path) -> None:
        md = tmp_path / "bad.md"
        md.write_text("---\ndescription: sem nome\n---\nconteudo")
        with pytest.raises(ValueError, match="name"):
            load_from_file(md)

    def test_missing_description_raises(self, tmp_path: Path) -> None:
        md = tmp_path / "bad.md"
        md.write_text("---\nname: sem_desc\n---\nconteudo")
        with pytest.raises(ValueError, match="description"):
            load_from_file(md)

    def test_hash_changes_when_content_changes(self, tmp_path: Path) -> None:
        md = tmp_path / "skill.md"
        md.write_text("---\nname: s\ndescription: d\n---\nv1")
        h1 = load_from_file(md).content_hash
        md.write_text("---\nname: s\ndescription: d\n---\nv2")
        h2 = load_from_file(md).content_hash
        assert h1 != h2


class TestLoadFromDir:
    def test_parses_valid_dir(self) -> None:
        skill = load_from_dir(FIXTURES / "valid_skill_dir")
        assert skill.name == "dir_skill"
        assert skill.arguments[0].name == "query"
        assert "Processe" in skill.prompt

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        (tmp_path / "prompt.md").write_text("p")
        with pytest.raises(FileNotFoundError, match="manifest.yaml"):
            load_from_dir(tmp_path)

    def test_missing_prompt_raises(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.yaml").write_text("name: x\ndescription: d")
        with pytest.raises(FileNotFoundError, match="prompt.md"):
            load_from_dir(tmp_path)

    def test_invalid_tools_py_raises(self) -> None:
        with pytest.raises(PermissionError, match="subprocess"):
            load_from_dir(FIXTURES / "invalid_tools_py")


class TestLoadAllFromDir:
    def test_loads_builtins(self) -> None:
        skills = load_all_from_dir(BUILTIN.parent)
        names = {s.name for s in skills}
        assert "summarize_text" in names
        assert "web_research" in names
        assert "file_inspect" in names
        assert "extract_skill" in names

    def test_duplicate_name_raises(self, tmp_path: Path) -> None:
        for i in range(2):
            f = tmp_path / f"skill_{i}.md"
            f.write_text("---\nname: same_name\ndescription: d\n---\np")
        with pytest.raises(ValueError, match="duplicado"):
            load_all_from_dir(tmp_path)

    def test_ignores_drafts_dir(self, tmp_path: Path) -> None:
        drafts = tmp_path / "_drafts"
        drafts.mkdir()
        (drafts / "draft.md").write_text(
            "---\nname: draft_skill\ndescription: d\n---\np"
        )
        # Sem skills fora de _drafts → lista vazia (não levanta)
        skills = load_all_from_dir(tmp_path)
        assert not any(s.name == "draft_skill" for s in skills)

    def test_ignores_invalid_but_continues(self, tmp_path: Path) -> None:
        good = tmp_path / "good.md"
        good.write_text("---\nname: ok\ndescription: d\n---\nprompt")
        bad = tmp_path / "bad.md"
        bad.write_text("sem frontmatter valido")
        # Só carrega a boa; a ruim é logada e ignorada
        skills = load_all_from_dir(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "ok"
