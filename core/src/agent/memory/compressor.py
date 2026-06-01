"""
ContextCompressor: comprime histórico longo via Sonnet 4.6.
Mantém as últimas N mensagens intactas e sumariza as anteriores.
"""

from __future__ import annotations

import os
import time
from typing import Any

from anthropic import AsyncAnthropic

from agent.observability.logger import get_logger

log = get_logger(__name__)

_COMPRESSOR_MODEL = os.getenv("MEMORY_COMPRESSOR_MODEL", "claude-sonnet-4-6-20250514")
_TOKEN_THRESHOLD = int(os.getenv("MEMORY_TOKEN_THRESHOLD", "8000"))
_KEEP_RECENT = int(os.getenv("MEMORY_KEEP_RECENT", "6"))

_SYSTEM = """\
Você é o Compressor de contexto de um agente autônomo. Receberá um bloco de \
mensagens antigas de uma conversa e deve produzir um RESUMO ESTRUTURADO em \
português que preserve:

1. Identidade e contexto do usuário (nome, projeto, stack)
2. Decisões tomadas e suas justificativas
3. Tarefas em andamento e seu status
4. Fatos relevantes mencionados (números, nomes, datas)
5. Tom/preferências de comunicação observados

NÃO inclua:
- Saudações, smalltalk
- Detalhes de execução de tools já resolvidos
- Conteúdo redundante

Formato: prosa estruturada com seções `## Identidade`, `## Decisões`, \
`## Tarefas`, `## Fatos`. Máximo 600 tokens.
"""


class ContextCompressor:
    def __init__(
        self,
        client: AsyncAnthropic | None = None,
        model: str = _COMPRESSOR_MODEL,
        token_threshold: int = _TOKEN_THRESHOLD,
        keep_recent: int = _KEEP_RECENT,
    ) -> None:
        self._client = client or AsyncAnthropic()
        self._model = model
        self._token_threshold = token_threshold
        self._keep_recent = keep_recent

    @staticmethod
    def _approx_tokens(messages: list[dict[str, Any]]) -> int:
        # ~4 chars por token; heurística conservadora
        total = sum(len(str(m.get("content", ""))) for m in messages)
        return total // 4

    async def maybe_compress(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
        """
        Retorna (mensagens_compactadas, texto_do_resumo_ou_None).
        Se não houver compressão necessária, retorna (mensagens_originais, None).
        """
        if self._approx_tokens(messages) <= self._token_threshold:
            return messages, None
        if len(messages) <= self._keep_recent + 2:
            return messages, None

        t0 = time.monotonic()
        recent = messages[-self._keep_recent :]
        old = messages[: -self._keep_recent]

        system_msgs = [m for m in old if m.get("role") == "system"]
        old_dialogue = [m for m in old if m.get("role") != "system"]

        summary = await self._summarize(old_dialogue)

        log.info(
            "compressor.applied",
            messages_in=len(old_dialogue),
            messages_out=len(recent),
            summary_len=len(summary),
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
        )

        compacted = (
            system_msgs
            + [
                {
                    "role": "system",
                    "content": f"<resumo_da_conversa>\n{summary}\n</resumo_da_conversa>",
                }
            ]
            + recent
        )
        return compacted, summary

    async def _summarize(self, messages: list[dict[str, Any]]) -> str:
        joined = "\n".join(f"[{m.get('role')}]: {str(m.get('content', ''))[:2000]}" for m in messages)
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{"role": "user", "content": joined}],
        )
        return resp.content[0].text.strip()
