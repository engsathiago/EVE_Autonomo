"""
Tabela de capabilities por modelo. Para Ollama, complementada por descoberta dinâmica.
"""
from __future__ import annotations

from agent.models.base import Capabilities

# ---------------------------------------------------------------------------
# Providers cloud — tabela estática
# ---------------------------------------------------------------------------

CLOUD_CAPABILITIES: dict[str, Capabilities] = {
    # Anthropic
    "anthropic:claude-sonnet-4-7": Capabilities(
        tool_use=True, vision=True, json_mode=True, streaming=True,
        max_context=200_000, parallel_tools=True,
    ),
    "anthropic:claude-opus-4-7": Capabilities(
        tool_use=True, vision=True, json_mode=True, streaming=True,
        max_context=200_000, parallel_tools=True,
    ),
    "anthropic:claude-haiku-4-5": Capabilities(
        tool_use=True, vision=True, json_mode=True, streaming=True,
        max_context=200_000, parallel_tools=True,
    ),
    "anthropic:claude-sonnet-4-6": Capabilities(
        tool_use=True, vision=True, json_mode=True, streaming=True,
        max_context=200_000, parallel_tools=True,
    ),
    # OpenAI
    "openai:gpt-4o": Capabilities(
        tool_use=True, vision=True, json_mode=True, streaming=True,
        max_context=128_000, parallel_tools=True,
    ),
    "openai:gpt-4o-mini": Capabilities(
        tool_use=True, vision=True, json_mode=True, streaming=True,
        max_context=128_000, parallel_tools=True,
    ),
    # OpenRouter — subset representativo
    "openrouter:anthropic/claude-3.5-sonnet": Capabilities(
        tool_use=True, vision=True, json_mode=True, streaming=True,
        max_context=200_000, parallel_tools=True,
    ),
    "openrouter:deepseek/deepseek-chat": Capabilities(
        tool_use=True, vision=False, json_mode=True, streaming=True,
        max_context=64_000, parallel_tools=False,
    ),
    "openrouter:meta-llama/llama-3.3-70b-instruct": Capabilities(
        tool_use=True, vision=False, json_mode=True, streaming=True,
        max_context=128_000, parallel_tools=False,
    ),
}

# ---------------------------------------------------------------------------
# Ollama — capabilities por família (fallback quando /api/show não retorna)
# ---------------------------------------------------------------------------
# Chaves são prefixos de model_id (sem provider:). Matching é "startswith".

OLLAMA_FAMILY_CAPABILITIES: list[tuple[str, Capabilities]] = [
    ("qwen2.5", Capabilities(
        tool_use=True, vision=False, json_mode=True, streaming=True,
        max_context=32_768, parallel_tools=False,
    )),
    ("qwen3", Capabilities(
        tool_use=True, vision=False, json_mode=True, streaming=True,
        max_context=32_768, parallel_tools=False,
    )),
    ("llama3", Capabilities(
        tool_use=True, vision=False, json_mode=True, streaming=True,
        max_context=128_000, parallel_tools=False,
    )),
    ("hermes3", Capabilities(
        tool_use=True, vision=False, json_mode=True, streaming=True,
        max_context=128_000, parallel_tools=False,
    )),
    ("mistral", Capabilities(
        tool_use=True, vision=False, json_mode=True, streaming=True,
        max_context=32_768, parallel_tools=False,
    )),
    ("deepseek-r1", Capabilities(
        tool_use=False, vision=False, json_mode=False, streaming=True,
        max_context=128_000, parallel_tools=False,
    )),
    ("deepseek-v3", Capabilities(
        tool_use=True, vision=False, json_mode=True, streaming=True,
        max_context=128_000, parallel_tools=False,
    )),
    ("gemma2", Capabilities(
        tool_use=False, vision=False, json_mode=False, streaming=True,
        max_context=8_192, parallel_tools=False,
    )),
    ("phi4", Capabilities(
        tool_use=False, vision=False, json_mode=True, streaming=True,
        max_context=16_384, parallel_tools=False,
    )),
    ("codellama", Capabilities(
        tool_use=False, vision=False, json_mode=False, streaming=True,
        max_context=16_384, parallel_tools=False,
    )),
]

_OLLAMA_FALLBACK = Capabilities(
    tool_use=False, vision=False, json_mode=False, streaming=True,
    max_context=4_096, parallel_tools=False,
)


def get_cloud_capabilities(alias: str) -> Capabilities | None:
    """Retorna capabilities para alias 'provider:model'. None se desconhecido."""
    return CLOUD_CAPABILITIES.get(alias)


def get_ollama_family_capabilities(model_id: str) -> Capabilities:
    """Retorna capabilities para modelo Ollama por família. Fallback conservador se família desconhecida."""
    for prefix, caps in OLLAMA_FAMILY_CAPABILITIES:
        if model_id.startswith(prefix):
            return caps
    return _OLLAMA_FALLBACK
