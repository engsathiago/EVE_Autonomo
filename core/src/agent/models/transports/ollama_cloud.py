"""
Transport Ollama Cloud — provider separado do ollama local.

Usa a API nativa Ollama (/api/chat) via https://ollama.com com autenticação Bearer.
Diferenças do OllamaTransport local:
  - api_key obrigatória (ValueError se ausente)
  - base_url default: https://ollama.com
  - name = "ollama_cloud" (registrado como provider independente no router)
"""

from __future__ import annotations

import httpx

from agent.models.base import ModelInfo
from agent.models.transports.ollama import OllamaTransport


class OllamaCloudTransport(OllamaTransport):
    """Transport para Ollama Cloud (ollama.com).

    Idêntico ao OllamaTransport em protocolo e formato de payload.
    Registrado no router como provider "ollama_cloud" para distinguir do
    ollama local — permite usar ambos simultaneamente (ex: fallback chain
    "ollama_cloud:deepseek-v3.1:cloud,ollama:qwen2.5:7b").
    """

    name = "ollama_cloud"

    def __init__(
        self,
        base_url: str = "https://ollama.com",
        api_key: str = "",
        timeout: int = 120,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "OllamaCloudTransport requer autenticação. "
                "Defina OLLAMA_CLOUD_API_KEY no .env com a chave de "
                "https://ollama.com/settings/keys."
            )
        super().__init__(base_url=base_url, api_key=api_key, timeout=timeout, http_client=http_client)

    async def list_models(self) -> list[ModelInfo]:
        models = await super().list_models()
        for m in models:
            m.provider = "ollama_cloud"
        return models
