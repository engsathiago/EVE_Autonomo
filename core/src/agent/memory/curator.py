"""
Curator: decide se um turno de conversa vale a pena persistir.
Usa Haiku 4.5 com saída JSON estruturada.
"""
from __future__ import annotations

import json
import os
import time

from anthropic import AsyncAnthropic

from agent.memory.schemas import CuratorDecision
from agent.observability.logger import get_logger

log = get_logger(__name__)

_CURATOR_MODEL = os.getenv("MEMORY_CURATOR_MODEL", "claude-haiku-4-5-20251001")

_SYSTEM = """\
Você é o Curator de memória de um agente autônomo. Sua função é decidir se um \
turno de conversa contém informação que valha a pena ser lembrada em sessões futuras.

CRITÉRIOS PARA PERSISTIR:
- Fatos sobre o usuário (preferências, projetos, contexto profissional/pessoal)
- Decisões tomadas que afetam o futuro (escolhas de stack, arquitetura)
- Resultados de tarefas que podem ser referenciados depois
- Aprendizados sobre o domínio que o agente deve carregar

CRITÉRIOS PARA NÃO PERSISTIR:
- Saudações, agradecimentos, smalltalk
- Perguntas factuais com resposta autocontida
- Conteúdo já trivialmente disponível (ex: "qual a capital da França")
- Redundâncias com memórias já existentes (sinalizadas no contexto)

CLASSIFICAÇÃO `kind`:
- fact: fato objetivo
- preference: preferência/opinião do usuário
- decision: decisão arquitetural/de projeto
- summary: resumo de bloco longo
- note: observação livre

IMPORTANCE (1-10):
- 1-3: trivial, descartável
- 4-6: útil, contexto operacional
- 7-9: crítico, decisões/preferências fortes
- 10: identidade/projeto core

Responda APENAS com JSON válido, sem markdown:
{"persist": bool, "reason": "explicação curta", "importance": int, \
"kind": "fact|preference|decision|summary|note", \
"extracted_content": "texto sintético a salvar ou null"}
"""


class Curator:
    def __init__(
        self,
        client: AsyncAnthropic | None = None,
        model: str = _CURATOR_MODEL,
    ) -> None:
        self._client = client or AsyncAnthropic()
        self._model = model

    async def should_persist(
        self,
        user_msg: str,
        assistant_msg: str,
        existing_memories: list[str] | None = None,
    ) -> CuratorDecision:
        t0 = time.monotonic()
        ctx_block = ""
        if existing_memories:
            ctx_block = "\n\nMEMÓRIAS JÁ EXISTENTES (evite duplicar):\n" + "\n".join(
                f"- {m}" for m in existing_memories[:10]
            )

        content = (
            f"TURNO A AVALIAR:\n[user]: {user_msg}\n[assistant]: {assistant_msg}{ctx_block}"
        )

        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=_SYSTEM,
                messages=[{"role": "user", "content": content}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").lstrip("json").strip()
            data = json.loads(raw)
            decision = CuratorDecision(**data)
            log.info(
                "curator.decision",
                persist=decision.persist,
                kind=decision.kind,
                importance=decision.importance,
                reason=decision.reason,
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
            )
            return decision
        except Exception as exc:
            log.warning("curator.failed", error=str(exc))
            return CuratorDecision(persist=False, reason=f"curator_error: {exc}", importance=1)
