"""
Critic Autônomo: colegiado de 3 personas avaliando decisões irreversíveis.

Fluxo:
  Técnico + Advogado do Diabo → asyncio.gather (paralelo)
  Sintetizador recebe os 3 pareceres prontos → decide veredito final

Anti-padrão proibido: Sintetizador NÃO sabe quais são os pareceres antes
de gerar o seu. Recebe os 3 prontos como input (já computados).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from agent.critic.irreversible import is_irreversible
from agent.observability.logger import get_logger
from agent.orchestrator.tiers import ExecutionTier

if TYPE_CHECKING:
    from agent.models.router import ModelRouter

log = get_logger(__name__)

_VERDICT_CACHE_TTL_S = 60  # mesma decisão idêntica em 60s = mesmo veredito


@dataclass
class Decision:
    """Representa uma decisão pendente de avaliação pelo Critic."""

    tool_name: str
    tool_args: dict[str, Any]
    context_summary: str  # prosa descrevendo por que o agente quer fazer isso
    tier: ExecutionTier = ExecutionTier.FAST
    estimated_cost_usd: float = 0.0
    affects_external_world: bool = False
    is_first_of_its_kind: bool = False
    mission_id: UUID | None = None
    task_id: UUID | None = None
    decision_id: UUID = field(default_factory=uuid4)

    def cache_key(self) -> str:
        payload = json.dumps({"tool": self.tool_name, "args": self.tool_args}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class PersonaVerdict:
    approve: bool
    confidence: float  # 0.0–1.0
    reasoning: str
    concerns: list[str]


@dataclass
class CriticVerdict:
    verdict: str  # approve | reject | approve_with_mitigation | escalate
    mitigations: list[str]
    reasoning: str
    escalation_message: str
    technical: PersonaVerdict
    devils_advocate: PersonaVerdict
    synthesizer_raw: dict[str, Any]


class CriticRejected(Exception):
    def __init__(self, reasoning: str) -> None:
        super().__init__(f"Critic rejeitou a decisão: {reasoning}")
        self.reasoning = reasoning


_TECHNICAL_PROMPT = """\
Você revisa decisões técnicas de um agente autônomo. Avalie:
- A decisão é tecnicamente correta dado o estado do sistema?
- Os args da tool fazem sentido? Há valores fora do esperado?
- Há condição de corrida, dependência não resolvida, side effect não considerado?
- O agente entende a tool que está usando, ou está chutando?

Tool: {tool_name}
Args: {tool_args}
Contexto: {context}

Retorne APENAS JSON válido:
{{"approve": true|false, "confidence": 0.0-1.0, "reasoning": "...", "concerns": ["..."]}}
Aprove só se a decisão for tecnicamente sólida."""

_DEVILS_ADVOCATE_PROMPT = """\
Você é o advogado do diabo. Encontre pelo menos 3 razões para NÃO executar essa decisão.
- E se o pressuposto principal estiver errado?
- Quem se prejudica se isso for executado?
- O que acontece no pior caso?
- Existe versão menor/reversível que dá a mesma informação?

Tool: {tool_name}
Args: {tool_args}
Contexto: {context}

Retorne APENAS JSON válido:
{{"approve": true|false, "confidence": 0.0-1.0, "reasoning": "...", "concerns": ["..."]}}
Default é não aprovar. Só aprove se TODAS as objeções tiverem sido respondidas no contexto."""

_SYNTHESIZER_PROMPT = """\
Você recebe pareceres do Técnico e do Advogado do Diabo mais o contexto da decisão.
Sua função NÃO é votar — é DECIDIR.

Regras:
- Se ambos aprovam com confidence >= 0.7 → veredito = "approve"
- Se ambos rejeitam → veredito = "reject"
- Se discordam → APPROVE_WITH_MITIGATION (liste mitigações)
  ou ESCALATE_TO_HUMAN se genuinamente ambíguo
- NUNCA invente meio-termo que ignora a concern principal

Contexto: {context}
Tool: {tool_name}
Args: {tool_args}

Parecer Técnico: {technical}
Parecer Advogado do Diabo: {devils}

Retorne APENAS JSON válido:
{{"verdict": "approve|reject|approve_with_mitigation|escalate",
  "mitigations": [],
  "reasoning": "...",
  "escalation_message": ""}}"""


def needs_critic(
    decision: Decision,
    cost_threshold_usd: float = 0.50,
) -> bool:
    return (
        is_irreversible(decision.tool_name)
        or decision.tier == ExecutionTier.EPIC
        or decision.estimated_cost_usd >= cost_threshold_usd
        or decision.affects_external_world
        or decision.is_first_of_its_kind
    )


class Critic:
    def __init__(
        self,
        model_router: ModelRouter,
        medium_model: str = "ollama_cloud:gpt-oss:20b-cloud",
        primary_model: str = "ollama_cloud:kimi-k2.5:cloud",
        cost_threshold_usd: float = 0.50,
    ) -> None:
        self._router = model_router
        self._medium_model = medium_model
        self._primary_model = primary_model
        self._cost_threshold = cost_threshold_usd
        # Cache: decision_hash → (verdict, timestamp)
        self._cache: dict[str, tuple[CriticVerdict, float]] = {}

    async def evaluate(
        self,
        decision: Decision,
        *,
        db_pool: Any = None,
    ) -> CriticVerdict:
        """
        Avalia a decisão com 3 personas em paralelo.
        Resultado é cacheado por 60s para decisões idênticas.
        Persiste em critic_evaluations se db_pool fornecido.
        """
        cache_key = decision.cache_key()
        cached = self._cache.get(cache_key)
        if cached and (time.monotonic() - cached[1]) < _VERDICT_CACHE_TTL_S:
            log.debug("critic.cache_hit", key=cache_key)
            return cached[0]

        t0 = time.monotonic()

        technical, devils = await asyncio.gather(
            self._run_technical(decision),
            self._run_devils_advocate(decision),
        )
        synthesizer_raw = await self._run_synthesizer(decision, technical, devils)

        verdict = CriticVerdict(
            verdict=synthesizer_raw.get("verdict", "reject"),
            mitigations=synthesizer_raw.get("mitigations", []),
            reasoning=synthesizer_raw.get("reasoning", ""),
            escalation_message=synthesizer_raw.get("escalation_message", ""),
            technical=technical,
            devils_advocate=devils,
            synthesizer_raw=synthesizer_raw,
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "critic.evaluated",
            tool=decision.tool_name,
            verdict=verdict.verdict,
            latency_ms=latency_ms,
        )

        self._cache[cache_key] = (verdict, time.monotonic())

        if db_pool is not None:
            await self._persist(decision, verdict, latency_ms, db_pool)

        return verdict

    async def _run_technical(self, decision: Decision) -> PersonaVerdict:
        prompt = _TECHNICAL_PROMPT.format(
            tool_name=decision.tool_name,
            tool_args=json.dumps(decision.tool_args, ensure_ascii=False),
            context=decision.context_summary[:1500],
        )
        return await self._call_persona(prompt, model=self._medium_model)

    async def _run_devils_advocate(self, decision: Decision) -> PersonaVerdict:
        prompt = _DEVILS_ADVOCATE_PROMPT.format(
            tool_name=decision.tool_name,
            tool_args=json.dumps(decision.tool_args, ensure_ascii=False),
            context=decision.context_summary[:1500],
        )
        return await self._call_persona(prompt, model=self._medium_model)

    async def _run_synthesizer(
        self,
        decision: Decision,
        technical: PersonaVerdict,
        devils: PersonaVerdict,
    ) -> dict[str, Any]:
        prompt = _SYNTHESIZER_PROMPT.format(
            context=decision.context_summary[:1500],
            tool_name=decision.tool_name,
            tool_args=json.dumps(decision.tool_args, ensure_ascii=False),
            technical=json.dumps(
                {
                    "approve": technical.approve,
                    "confidence": technical.confidence,
                    "reasoning": technical.reasoning,
                    "concerns": technical.concerns,
                },
                ensure_ascii=False,
            ),
            devils=json.dumps(
                {
                    "approve": devils.approve,
                    "confidence": devils.confidence,
                    "reasoning": devils.reasoning,
                    "concerns": devils.concerns,
                },
                ensure_ascii=False,
            ),
        )
        try:
            response = await self._router.chat(
                system="Você decide vereditos. Retorne apenas JSON válido.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                model=self._primary_model,
            )
            raw = response.text.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1:
                return json.loads(raw[start:end])
            return {"verdict": "reject", "reasoning": raw}
        except Exception as exc:
            log.warning("critic.synthesizer.failed", error=str(exc))
            return {
                "verdict": "reject",
                "reasoning": f"Sintetizador falhou: {exc}",
                "mitigations": [],
                "escalation_message": "",
            }

    async def _call_persona(self, prompt: str, *, model: str) -> PersonaVerdict:
        try:
            response = await self._router.chat(
                system="Você avalia decisões de agentes autônomos. Retorne apenas JSON válido.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                model=model,
            )
            raw = response.text.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end]) if start != -1 else {}
            return PersonaVerdict(
                approve=bool(data.get("approve", False)),
                confidence=float(data.get("confidence", 0.0)),
                reasoning=data.get("reasoning", ""),
                concerns=data.get("concerns", []),
            )
        except Exception as exc:
            log.warning("critic.persona.failed", error=str(exc))
            return PersonaVerdict(
                approve=False,
                confidence=0.0,
                reasoning=f"Persona falhou: {exc}",
                concerns=["Falha ao avaliar — rejeição defensiva"],
            )

    async def request_approval(
        self,
        command: list[str] | str,
        policy_name: str,
    ) -> bool:
        """
        Avalia se um comando pode ser executado sob a política dada.

        Cria uma Decision sintética e passa pelo Conclave. Retorna True se
        aprovado (approve ou approve_with_mitigation), False caso contrário.
        Chamado por exec_tool quando SandboxPolicy.require_critic_approval=True.
        """
        cmd_str = command if isinstance(command, str) else " ".join(command)
        decision = Decision(
            tool_name="exec_sandbox",
            tool_args={"command": cmd_str[:200], "policy": policy_name},
            context_summary=(f"Execução de comando em sandbox com política '{policy_name}'. Comando: {cmd_str[:300]}"),
            affects_external_world=True,
            is_first_of_its_kind=True,
        )
        verdict = await self.evaluate(decision)
        approved = verdict.verdict in ("approve", "approve_with_mitigation")
        log.info(
            "critic.sandbox_approval",
            policy=policy_name,
            verdict=verdict.verdict,
            approved=approved,
        )
        return approved

    async def _persist(
        self,
        decision: Decision,
        verdict: CriticVerdict,
        latency_ms: int,
        pool: Any,
    ) -> None:
        try:
            await pool.execute(
                """
                INSERT INTO critic_evaluations
                    (decision_id, task_id, mission_id,
                     technical_verdict, devils_advocate_verdict, synthesizer_verdict,
                     final_verdict, mitigations, latency_ms)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8::jsonb, $9)
                """,
                decision.decision_id,
                decision.task_id,
                decision.mission_id,
                json.dumps(
                    {
                        "approve": verdict.technical.approve,
                        "confidence": verdict.technical.confidence,
                        "reasoning": verdict.technical.reasoning,
                        "concerns": verdict.technical.concerns,
                    }
                ),
                json.dumps(
                    {
                        "approve": verdict.devils_advocate.approve,
                        "confidence": verdict.devils_advocate.confidence,
                        "reasoning": verdict.devils_advocate.reasoning,
                        "concerns": verdict.devils_advocate.concerns,
                    }
                ),
                json.dumps(verdict.synthesizer_raw),
                verdict.verdict,
                json.dumps(verdict.mitigations),
                latency_ms,
            )
        except Exception as exc:
            log.warning("critic.persist.failed", error=str(exc))
