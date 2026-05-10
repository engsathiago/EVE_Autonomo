"""
MissionPlanner: decompõe um objetivo em linguagem natural em passos executáveis.

Antes de planejar, consulta ReflexiveMemory para enriquecer o contexto com
lições aprendidas de missões anteriores similares.

Não cria a missão — só monta o plano. Quem cria é quem chamou.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.memory.reflexive import ReflexiveMemory
    from agent.models.router import ModelRouter

log = get_logger(__name__)

_PLANNER_PROMPT = """\
Você é um planejador de missões. Recebe um objetivo em prosa e devolve JSON com:
- title: <80 chars, descritivo
- success_criteria: lista de objetos {{"criterion": "...", "verifiable_via": "manual|metric|task"}}
- steps: lista ordenada de descrições curtas (<200 chars cada), cada uma viável como uma task

REGRAS:
1. Cada critério em success_criteria precisa ser verificável por alguém que NÃO leu este prompt.
   Errado: "fazer um bom canal". Certo: "publicar 10 cortes em 30 dias".
2. Steps são SEQUENCIAIS por padrão. Marque step com prefixo "[PARALELO N]:" se pode rodar
   em paralelo com os N steps seguintes.
3. Não invente passos genéricos tipo "fazer pesquisa". Especifique sobre o quê.
4. Se objetivo não tem como virar critérios verificáveis, devolve:
   {{"error": "objetivo_subjetivo", "reason": "..."}}

{reflexive_context}

Objetivo: {objective}
{deadline_hint}

Retorne APENAS JSON válido. Nada mais."""

_REPLANNER_PROMPT = """\
Você é um planejador de missões em modo de re-planejamento.

Uma missão falhou em algum ponto. Seu trabalho é gerar novos steps a partir do estado atual.
Os success_criteria originais são mantidos — não os altere.

Missão: {title}
Objetivo: {objective}
Critérios de sucesso (mantidos): {criteria}
Motivo do replan: {reason}
Steps já concluídos: {done_steps}
Steps que falharam: {failed_steps}

Gere APENAS os steps faltantes. Retorne JSON:
{{"steps": ["descrição step 1", "descrição step 2", ...]}}
Nada mais."""


@dataclass
class MissionPlan:
    title: str
    success_criteria: list[dict[str, Any]]
    steps: list[str]
    is_parallel: list[bool] = field(default_factory=list)  # True se step tem prefixo [PARALELO]

    def __post_init__(self) -> None:
        if not self.is_parallel:
            self.is_parallel = [False] * len(self.steps)


class ObjectiveSubjectiveError(Exception):
    """Objetivo não tem critérios verificáveis — requer refinamento do usuário."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Objetivo subjetivo: {reason}")
        self.reason = reason


class MissionPlanner:
    def __init__(
        self,
        model_router: ModelRouter,
        reflexive_memory: ReflexiveMemory | None = None,
        model: str = "anthropic:claude-haiku-4-5",
        max_tokens: int = 1200,
    ) -> None:
        self._router = model_router
        self._reflexive_memory = reflexive_memory
        self._model = model
        self._max_tokens = max_tokens

    async def plan(
        self,
        objective: str,
        deadline: datetime | None = None,
    ) -> MissionPlan:
        reflexive_context = ""
        if self._reflexive_memory is not None:
            try:
                insights = await self._reflexive_memory.recall(objective, top_k=3)
                if insights:
                    lines = "\n".join(f"- {i.insight}" for i in insights)
                    reflexive_context = f"Lições de missões anteriores:\n{lines}\n"
            except Exception as exc:
                log.warning("planner.reflexive_recall.failed", error=str(exc))

        deadline_hint = ""
        if deadline:
            delta = deadline - datetime.now(tz=deadline.tzinfo)
            days = max(0, delta.days)
            deadline_hint = f"Prazo: {deadline.strftime('%Y-%m-%d')} ({days} dias restantes)."

        prompt = _PLANNER_PROMPT.format(
            objective=objective[:2000],
            deadline_hint=deadline_hint,
            reflexive_context=reflexive_context,
        )

        raw = await self._call_llm(prompt)
        return self._parse_plan(raw)

    async def replan(
        self,
        mission_id: UUID,
        *,
        reason: str,
        mission_store: Any = None,
    ) -> MissionPlan:
        """Re-plana a partir do estado atual da missão. Preserva success_criteria original."""
        if mission_store is None:
            raise ValueError("mission_store é obrigatório para replan")

        mission = await mission_store.get(mission_id)
        all_steps = await mission_store.get_all_steps(mission_id)

        done_steps = [s.description for s in all_steps if s.status == "done"]
        failed_steps = [s.description for s in all_steps if s.status == "failed"]

        prompt = _REPLANNER_PROMPT.format(
            title=mission.title,
            objective=mission.objective,
            criteria=json.dumps(mission.success_criteria, ensure_ascii=False),
            reason=reason,
            done_steps=json.dumps(done_steps, ensure_ascii=False),
            failed_steps=json.dumps(failed_steps, ensure_ascii=False),
        )

        raw = await self._call_llm(prompt)
        data = self._safe_parse(raw)

        steps = data.get("steps", [])
        if not steps:
            raise ValueError("Replan gerou lista de steps vazia")

        cleaned, parallel_flags = _extract_parallel(steps)

        # Preserva success_criteria da missão original
        return MissionPlan(
            title=mission.title,
            success_criteria=mission.success_criteria,
            steps=cleaned,
            is_parallel=parallel_flags,
        )

    async def _call_llm(self, prompt: str) -> str:
        response = await self._router.chat(
            system="Você planeja missões. Retorne apenas JSON válido.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self._max_tokens,
            model=self._model,
        )
        return response.text.strip()

    def _parse_plan(self, raw: str) -> MissionPlan:
        data = self._safe_parse(raw)

        if "error" in data and data["error"] == "objetivo_subjetivo":
            raise ObjectiveSubjectiveError(data.get("reason", "objetivo não verificável"))

        title = data.get("title", "Missão sem título")[:80]
        criteria = data.get("success_criteria", [])
        steps_raw = data.get("steps", [])

        if not criteria:
            raise ObjectiveSubjectiveError("Planner não gerou critérios verificáveis")

        if not steps_raw:
            raise ValueError("Planner gerou lista de steps vazia")

        steps, parallel_flags = _extract_parallel(steps_raw)

        return MissionPlan(
            title=title,
            success_criteria=criteria,
            steps=steps,
            is_parallel=parallel_flags,
        )

    def _safe_parse(self, raw: str) -> dict:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1:
            log.warning("planner.parse.no_json", raw=raw[:200])
            return {}
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError as exc:
            log.warning("planner.parse.invalid_json", error=str(exc), raw=raw[:200])
            return {}


def _extract_parallel(steps: list[str]) -> tuple[list[str], list[bool]]:
    """Remove prefixos [PARALELO N]: e retorna flags de paralelismo."""
    cleaned: list[str] = []
    flags: list[bool] = []
    for step in steps:
        if step.upper().startswith("[PARALELO"):
            colon = step.find(":")
            cleaned.append(step[colon + 1:].strip() if colon != -1 else step)
            flags.append(True)
        else:
            cleaned.append(step)
            flags.append(False)
    return cleaned, flags
