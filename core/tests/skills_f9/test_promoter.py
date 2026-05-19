"""Testes do SkillPromoter — C4: Crítico decide promoção."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.skills.manifest import SkillManifestF9
from agent.skills.promoter import SkillPromoter


def _manifest(slug: str = "test_skill") -> SkillManifestF9:
    return SkillManifestF9(
        slug=slug,
        version=1,
        created_at=datetime.now(tz=timezone.utc),
        description="test",
        embedding_text="test",
        inputs_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        outputs_schema={"type": "object", "properties": {"y": {"type": "string"}}, "required": ["y"]},
        sandbox_profile="SKILL_DEV",
        network_policy={"allow_domains": []},
    )


def _make_verdict(verdict: str) -> MagicMock:
    v = MagicMock()
    v.verdict = verdict
    v.reasoning = "test reasoning"
    return v


@pytest.mark.asyncio
async def test_promote_force_skips_critic(tmp_path: Path) -> None:
    """force=True deve pular o Crítico e aprovar diretamente."""
    registry = MagicMock()
    registry.get = AsyncMock()
    registry.update_status = AsyncMock()
    critic = MagicMock()
    critic.evaluate = AsyncMock()

    promoter = SkillPromoter(
        registry=registry,
        pending_dir=tmp_path / "pending",
        active_dir=tmp_path / "active",
        rejected_dir=tmp_path / "rejected",
        critic=critic,
    )

    approved = await promoter.promote(_manifest(), force=True)
    assert approved is True
    critic.evaluate.assert_not_awaited()
    registry.update_status.assert_awaited_once_with(
        "test_skill", "active", critic_approval_id="force"
    )


@pytest.mark.asyncio
async def test_promote_no_critic_auto_approves(tmp_path: Path) -> None:
    """Sem Crítico configurado, promove automaticamente."""
    registry = MagicMock()
    registry.update_status = AsyncMock()
    promoter = SkillPromoter(
        registry=registry,
        pending_dir=tmp_path / "pending",
        active_dir=tmp_path / "active",
        rejected_dir=tmp_path / "rejected",
        critic=None,
    )
    approved = await promoter.promote(_manifest())
    assert approved is True


@pytest.mark.asyncio
async def test_promote_critic_approve(tmp_path: Path) -> None:
    """Crítico aprova → skill vai para active."""
    registry = MagicMock()
    registry.update_status = AsyncMock()
    critic = MagicMock()
    critic.evaluate = AsyncMock(return_value=_make_verdict("approve"))

    promoter = SkillPromoter(
        registry=registry,
        pending_dir=tmp_path / "pending",
        active_dir=tmp_path / "active",
        rejected_dir=tmp_path / "rejected",
        critic=critic,
    )
    approved = await promoter.promote(_manifest())
    assert approved is True
    registry.update_status.assert_awaited_once()
    args = registry.update_status.call_args[0]
    assert args[1] == "active"


@pytest.mark.asyncio
async def test_promote_critic_reject(tmp_path: Path) -> None:
    """Crítico rejeita → skill vai para rejected."""
    registry = MagicMock()
    registry.update_status = AsyncMock()
    critic = MagicMock()
    critic.evaluate = AsyncMock(return_value=_make_verdict("reject"))

    promoter = SkillPromoter(
        registry=registry,
        pending_dir=tmp_path / "pending",
        active_dir=tmp_path / "active",
        rejected_dir=tmp_path / "rejected",
        critic=critic,
    )
    approved = await promoter.promote(_manifest())
    assert approved is False
    args = registry.update_status.call_args[0]
    assert args[1] == "rejected"


@pytest.mark.asyncio
async def test_promote_moves_files(tmp_path: Path) -> None:
    """Approve deve mover arquivos de _pending para _active."""
    slug = "test_skill"
    pending = tmp_path / "pending" / slug
    pending.mkdir(parents=True)
    (pending / "skill.py").write_text("# skill", encoding="utf-8")

    registry = MagicMock()
    registry.update_status = AsyncMock()
    promoter = SkillPromoter(
        registry=registry,
        pending_dir=tmp_path / "pending",
        active_dir=tmp_path / "active",
        rejected_dir=tmp_path / "rejected",
        critic=None,
    )
    await promoter.promote(_manifest(slug))

    assert not pending.exists()
    assert (tmp_path / "active" / slug / "skill.py").exists()
