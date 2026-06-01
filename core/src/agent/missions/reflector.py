"""
MissionReflector: roda uma vez quando missão atinge status terminal.

Parse estrito: exige exatamente 4 seções (ENTREGUE / QUALIDADE / PRÓXIMO / APRENDIDO).
Formato livre → exception. Reflexão sem 4 campos não vai para memória reflexiva.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from agent.missions.store import MissionReflection
from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.memory.reflexive import ReflexiveMemory
    from agent.missions.store import MissionStore
    from agent.models.router import ModelRouter

log = get_logger(__name__)

_REFLECTOR_PROMPT = """\
Você reflete sobre uma missão concluída. Responda nos 4 campos abaixo, exatamente nesta ordem.

Missão: {title}
Objetivo: {objective}
Critérios: {criteria}
Status final: {status}

Steps executados:
{steps_summary}

Avaliações do Critic (se houver):
{critic_summary}

Responda EXATAMENTE neste formato (sem markdown, sem JSON, sem campos extras):

ENTREGUE:
<O que de fato saiu da missão. Lista factual, sem adjetivos.>

QUALIDADE:
<Avaliação honesta. Se o resultado foi medíocre, diz medíocre. Se faltou critério, diz qual.>

PRÓXIMO:
<Uma única ação concreta que faria sentido fazer agora. Deixe em branco se nada faz sentido.>

APRENDIDO:
<Um insight ÚTIL pra missões futuras. Não é "fui bem-sucedido".
É "descobri que X falha quando Y".>"""

_SECTION_RE = re.compile(
    r"ENTREGUE:\s*(.*?)(?=\nQUALIDADE:|\Z)"
    r".*?QUALIDADE:\s*(.*?)(?=\nPRÓXIMO:|\Z)"
    r".*?PRÓXIMO:\s*(.*?)(?=\nAPRENDIDO:|\Z)"
    r".*?APRENDIDO:\s*(.*?)(?=\Z)",
    re.DOTALL,
)


class ReflectionParseError(Exception):
    """LLM não respeitou o formato dos 4 campos obrigatórios."""

    def __init__(self, raw: str) -> None:
        super().__init__(
            f"Reflector recebeu formato livre — 4 campos obrigatórios ausentes.\nRaw (truncado): {raw[:300]}"
        )
        self.raw = raw


class MissionReflector:
    def __init__(
        self,
        model_router: ModelRouter,
        mission_store: MissionStore,
        reflexive_memory: ReflexiveMemory,
        model: str = "anthropic:claude-sonnet-4-6",
        max_tokens: int = 800,
    ) -> None:
        self._router = model_router
        self._mission_store = mission_store
        self._reflexive_memory = reflexive_memory
        self._model = model
        self._max_tokens = max_tokens

    async def reflect(self, mission_id: UUID) -> MissionReflection:
        mission = await self._mission_store.get(mission_id)
        steps = await self._mission_store.get_all_steps(mission_id)
        critic_evals = await self._mission_store.get_critic_history(mission_id)

        prompt = self._build_prompt(mission, steps, critic_evals)
        response = await self._router.chat(
            system=(
                "Você reflete sobre missões de um agente autônomo. "
                "Siga exatamente o formato solicitado com os 4 campos."
            ),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self._max_tokens,
            model=self._model,
        )
        raw = response.text.strip()
        reflection = self._parse_strict(raw, mission_id=mission_id)

        await self._mission_store.add_reflection(mission_id, reflection)
        await self._reflexive_memory.add(
            reflection.learned,
            source_mission=mission_id,
        )
        log.info(
            "mission.reflected",
            mission_id=str(mission_id),
            insight=reflection.learned[:100],
        )
        return reflection

    def _build_prompt(self, mission, steps, critic_evals) -> str:
        steps_lines = "\n".join(f"  [{s.status.upper()}] seq={s.sequence}: {s.description}" for s in steps)
        if not steps_lines:
            steps_lines = "  (nenhum step registrado)"

        critic_lines = (
            "\n".join(
                f"  [{e.get('final_verdict', '?').upper()}] {e.get('synthesizer_verdict', {})}"
                for e in critic_evals[:5]
            )
            if critic_evals
            else "  (nenhuma avaliação)"
        )

        import json

        return _REFLECTOR_PROMPT.format(
            title=mission.title,
            objective=mission.objective,
            criteria=json.dumps(mission.success_criteria, ensure_ascii=False),
            status=mission.status,
            steps_summary=steps_lines,
            critic_summary=critic_lines,
        )

    def _parse_strict(self, raw: str, *, mission_id: UUID) -> MissionReflection:
        match = _SECTION_RE.search(raw)
        if not match:
            raise ReflectionParseError(raw)

        delivered = match.group(1).strip()
        quality = match.group(2).strip()
        next_action = match.group(3).strip() or None
        learned = match.group(4).strip()

        if not delivered or not quality or not learned:
            raise ReflectionParseError(raw)

        return MissionReflection(
            id=uuid4(),
            mission_id=mission_id,
            delivered=delivered,
            quality_assessment=quality,
            next_action=next_action,
            learned=learned,
        )
