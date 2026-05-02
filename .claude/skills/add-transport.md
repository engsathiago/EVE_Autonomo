# Adicionar um Transport (provider de LLM) novo

## Quando usar
Quando o usuário pedir suporte a um novo provider (Gemini, Mistral, etc.)

## Passos
1. Crie `core/src/agent/transports/{nome}.py`
2. Herde de `BaseTransport` (em `transports/base.py`)
3. Implemente `async chat(system, messages, tools, **kwargs)` retornando
   `{"text", "tool_calls", "raw"}`
4. Converta o formato de tools do Anthropic-style pro formato do provider
5. Registre em `transports/registry.py`
6. Adicione config em `config/config.yaml` em `providers.{nome}`
7. Crie teste mock em `core/tests/transports/test_{nome}.py`

## Padrão
Veja `transports/anthropic.py` como referência canônica.
