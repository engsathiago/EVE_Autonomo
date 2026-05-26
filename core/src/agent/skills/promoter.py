"""
SkillPromoter (Fase 9): integra skill candidata com o Crítico (F7).

Fluxo:
  1. Skill passou validação local → status=validating
  2. SkillPromoter monta Decision e envia ao Critic
  3. Critic.evaluate() → veredito
  4. approve → move para _active/, status=active, critic_approval_id preenchido
  5. reject → move para _rejected/, status=rejected, rejection_reason preenchido

Anti-padrão: não duplica lógica do Crítico. Usa a API existente.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.critic.critic import Critic
    from agent.skills.manifest import SkillManifestF9
    from agent.skills.registry import SkillRegistry

log = get_logger(__name__)


class SkillPromoter:
    def __init__(
        self,
        registry: SkillRegistry,
        pending_dir: Path,
        active_dir: Path,
        rejected_dir: Path,
        critic: Critic | None = None,
    ) -> None:
        self._registry = registry
        self._pending_dir = pending_dir
        self._active_dir = active_dir
        self._rejected_dir = rejected_dir
        self._critic = critic

    async def promote(
        self,
        manifest: SkillManifestF9,
        *,
        candidate_id: str | None = None,
        force: bool = False,
    ) -> bool:
        """
        Submete skill ao Crítico. Retorna True se aprovada, False se rejeitada.
        Se force=True, pula Crítico (requer intervenção manual explícita).
        """
        slug = manifest.slug
        log.info("promoter.promoting", slug=slug, force=force)

        if force or self._critic is None:
            return await self._approve(manifest, critic_approval_id="force" if force else None)

        decision = self._build_decision(manifest)
        verdict = await self._critic.evaluate(decision)

        if verdict.verdict in ("approve", "approve_with_mitigation"):
            approval_id = str(getattr(verdict, "decision_id", candidate_id or "unknown"))
            return await self._approve(manifest, critic_approval_id=approval_id)
        else:
            reason = verdict.reasoning[:500] if verdict.reasoning else "critic_rejected"
            await self._reject(manifest, reason=reason)
            return False

    async def _approve(self, manifest: SkillManifestF9, critic_approval_id: str | None) -> bool:
        slug = manifest.slug
        src = self._pending_dir / slug
        dst = self._active_dir / slug

        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            shutil.rmtree(src)

        await self._registry.update_status(slug, "active", critic_approval_id=critic_approval_id)
        log.info("promoter.approved", slug=slug, approval_id=critic_approval_id)
        return True

    async def _reject(self, manifest: SkillManifestF9, reason: str) -> None:
        slug = manifest.slug
        src = self._pending_dir / slug
        dst = self._rejected_dir / slug

        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            shutil.rmtree(src)
            reason_file = dst / "reason.txt"
            reason_file.write_text(reason, encoding="utf-8")

        await self._registry.update_status(slug, "rejected", rejection_reason=reason)
        log.info("promoter.rejected", slug=slug, reason=reason[:100])

    def _build_decision(self, manifest: SkillManifestF9) -> Any:
        from agent.critic.critic import Decision
        from agent.orchestrator.tiers import ExecutionTier

        return Decision(
            tool_name="skill_promotion",
            tool_args={"slug": manifest.slug, "version": manifest.version},
            context_summary=(
                f"Skill auto-gerada '{manifest.slug}' candidata a promoção. "
                f"Descrição: {manifest.description}. "
                f"Sandbox: {manifest.sandbox_profile}. "
                f"Irreversível: {manifest.irreversible}."
            ),
            tier=ExecutionTier.STRATEGIC,
            affects_external_world=bool(manifest.network_policy.allow_domains),
            is_first_of_its_kind=True,
        )
