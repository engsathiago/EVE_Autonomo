# Phase 4 — Multi-modelo (Anthropic + OpenAI + OpenRouter + Ollama)

> **Status:** spec • **Pré-requisito:** Fase 3 (Skills) concluída e validada com `skill_invocations` populando • **Estimativa:** 3–4h de Claude Code, ~$3 USD

---

## 1. Objetivo

Tirar o agente da dependência única do Anthropic e dar a ele **escolha real de modelo por chamada** — entre cloud (Anthropic, OpenAI, OpenRouter) e local (Ollama, com qualquer modelo que o usuário tenha puxado: Llama, Qwen, Hermes, DeepSeek, Mistral, etc.).

Não é só "trocar o provider". É construir uma **camada de transports** que:

1. Fala protocolo unificado (uma `Message`, um `ToolCall`, um `Usage`) independente do provider.
2. Permite **rotear por skill, por turno, ou por env var** — a Fase 3 já tem campo `model:` no manifest da skill, esta fase finalmente honra ele.
3. Faz **fallback automático** quando o primary falha (ex: Ollama down → cai pra Anthropic).
4. Loga **custo, latência e tokens** por invocação no Postgres.
5. Suporta **streaming** em todos os providers (UI da Fase 7 vai precisar).

Ao fim da fase você consegue:

```bash
agent run "resume isso aí" --model ollama:qwen2.5:32b
agent run "explica esse traceback" --model anthropic:claude-sonnet-4-7
agent run "traduz pra inglês" --model openrouter:deepseek/deepseek-chat
```

E uma skill com `model: ollama:hermes3:8b` no manifest é executada localmente; uma com `model: anthropic:claude-opus-4-7` vai pra cloud — sem você mexer em código.

---

## 2. Princípios de design

| Princípio | Por quê |
|---|---|
| **Um protocolo, N adapters** | Você escreve a lógica do agente uma vez. Trocar Anthropic por Ollama vira 1 linha de config. |
| **Capabilities flag por modelo** | Nem todo modelo tem tool use, vision, JSON mode. O `Transport` declara o que sabe fazer; o agente checa antes de chamar. |
| **Cloud e local são iguais** | Mesma interface pra `anthropic.messages.create` e `ollama.chat`. O resto do código nem sabe a diferença. |
| **Roteamento explícito > heurística mágica** | A escolha do modelo é declarativa: skill define, ou usuário passa `--model`, ou `DEFAULT_MODEL` do `.env`. Sem auto-router treinado. |
| **Fallback é opt-in, não default** | Cair de Ollama pra Anthropic custa dinheiro silenciosamente. Só faz se você ligar `MODEL_FALLBACK_CHAIN`. |
| **Custo entra no banco desde o dia 1** | Sem isso, na Fase 8 (cron + reflexão) você não sabe qual skill ficou cara. |

---

## 3. Arquitetura

```
┌──────────────────────────────────────────────────────────────┐
│                         AIAgent (Fase 1)                     │
│                                                              │
│   run(message, model_override=None) ──► resolve_model() ─┐   │
│                                                          │   │
└──────────────────────────────────────────────────────────┼───┘
                                                           ▼
                                  ┌──────────────────────────────┐
                                  │      ModelRouter (NOVO)      │
                                  │                              │
                                  │  - resolve("anthropic:...")  │
                                  │  - apply_fallback_chain()    │
                                  │  - check_capabilities()      │
                                  └──────────────┬───────────────┘
                                                 │
                ┌────────────────────────────────┼────────────────────────────────┐
                ▼                                ▼                                ▼
   ┌────────────────────┐         ┌────────────────────┐              ┌────────────────────┐
   │ AnthropicTransport │         │   OpenAITransport  │              │   OllamaTransport  │
   │  (refator Fase 1)  │         │       (NOVO)       │              │       (NOVO)       │
   └─────────┬──────────┘         └─────────┬──────────┘              └─────────┬──────────┘
             │                              │                                   │
             ▼                              ▼                                   ▼
       api.anthropic.com           api.openai.com /                  http://localhost:11434
                                   openrouter.ai/api/v1
                                                                               │
                                                                               ▼
                                                           ┌────────────────────────────────┐
                                                           │  Qualquer modelo Ollama:        │
                                                           │  qwen2.5, llama3.3, hermes3,    │
                                                           │  deepseek-r1, mistral, phi4,    │
                                                           │  granite, gemma2, codellama...  │
                                                           └────────────────────────────────┘

         ▼
   ┌────────────────────────────────┐
   │   model_invocations (banco)    │  ← log de cada chamada (latência, tokens, custo, modelo)
   └────────────────────────────────┘
```

### Protocolo unificado

Todo `Transport` implementa a mesma interface (`core/models/base.py`):

```python
class Transport(Protocol):
    name: str                          # "anthropic", "openai", "openrouter", "ollama"
    capabilities: Capabilities         # tool_use, vision, json_mode, streaming, max_context

    async def chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        stream: bool = False,
        **kwargs
    ) -> ChatResponse: ...

    async def list_models(self) -> list[ModelInfo]:
        """Lista modelos disponíveis. Pra Ollama, chama /api/tags. Pra cloud, hardcoded ou da API."""

    async def health(self) -> HealthStatus:
        """Ping rápido. Usado pelo router pra fallback."""
```

`Message`, `ToolSchema`, `ChatResponse`, `Capabilities`, `ModelInfo` são Pydantic. Cada Transport converte do formato proprietário do provider pra esse formato.

### Como o Hermes/OpenClaw fazem (referência)

Os dois usam basicamente o mesmo padrão que vamos construir:

- **Hermes (NousResearch)** → tem um `inference_provider` abstrato. Você declara `provider: ollama` ou `provider: openai_compatible` no config, e a engine não muda. O modelo vai no campo `model`.
- **OpenClaw** → mesma ideia, com `LLMConfig` que aceita string `provider/model` (ex: `ollama/llama3.3:70b`, `anthropic/claude-sonnet-4-7`).

Estamos construindo o equivalente, integrado ao seu sistema de Skills da Fase 3 e ao Postgres da Fase 2.

---

## 4. Arquivos a criar/modificar

### Novos arquivos

| Arquivo | Responsabilidade |
|---|---|
| `core/models/__init__.py` | Marker do módulo |
| `core/models/base.py` | Protocol `Transport`, dataclasses `Message`, `ToolCall`, `ChatResponse`, `Capabilities`, `ModelInfo`, `HealthStatus` |
| `core/models/router.py` | `ModelRouter`: resolve string `provider:model` → Transport, aplica fallback chain, valida capabilities |
| `core/models/registry.py` | Registro in-memory de transports instanciados, lazy-load |
| `core/models/transports/anthropic.py` | `AnthropicTransport` (refator do que já existe na Fase 1) |
| `core/models/transports/openai.py` | `OpenAITransport` — usa `openai` SDK, compatível com OpenAI direto E com OpenRouter (mesma API) |
| `core/models/transports/openrouter.py` | `OpenRouterTransport` — herda de `OpenAITransport`, muda só base_url e adiciona headers obrigatórios (HTTP-Referer, X-Title) |
| `core/models/transports/ollama.py` | `OllamaTransport` — usa `ollama` lib oficial, suporta tool use nos modelos que aceitam |
| `core/models/pricing.py` | Tabela de preço por modelo (USD/1M tokens input e output). Ollama = $0. |
| `core/models/capabilities.py` | Mapa modelo → capabilities (tool use? vision? max_context?). Pra Ollama, descobre via `/api/show`. |
| `core/memory/migrations/004_model_invocations.sql` | Migration: tabela `model_invocations` |
| `tests/models/test_router.py` | Resolução de string, fallback, capability check |
| `tests/models/test_anthropic.py` | Mock de api.anthropic.com |
| `tests/models/test_openai.py` | Mock de api.openai.com |
| `tests/models/test_openrouter.py` | Mock de openrouter.ai |
| `tests/models/test_ollama.py` | Mock de localhost:11434 (não exige Ollama rodando nos CI) |
| `tests/models/test_pricing.py` | Cálculo de custo por invocação |
| `tests/integration/test_real_ollama.py` | Teste opcional, marcado `@pytest.mark.integration`, pula se Ollama não responder |

### Arquivos a modificar

| Arquivo | Mudança |
|---|---|
| `core/agent.py` | Trocar dependência direta de Anthropic por `ModelRouter`. Adicionar `model_override` no `run()`. |
| `core/skills/runner.py` | Quando skill tem `model:` no manifest, passa pro router. Senão, usa `DEFAULT_MODEL`. |
| `core/skills/schema.py` | Validar campo `model` (regex `^(anthropic|openai|openrouter|ollama):.+$`). |
| `core/cli.py` | Adicionar flag `--model` em `agent run`. Adicionar comandos `model list`, `model health`, `model show <name>`, `model test <name>`. |
| `core/config.py` | Adicionar `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_BASE_URL` (default `http://localhost:11434`), `DEFAULT_MODEL`, `MODEL_FALLBACK_CHAIN`, `MODEL_TIMEOUT_S`. |
| `pyproject.toml` | Adicionar `openai>=1.50`, `ollama>=0.4`. Anthropic já tem. |
| `.env.example` | Documentar novas vars. |
| `docker-compose.yml` | (opcional, ver Seção 8) Adicionar serviço Ollama. |
| `CLAUDE.md` | Atualizar status, padrão de string `provider:model`, tabela de modelos suportados, fallback. |
| `docs/architecture.md` | Seção "Multi-modelo: transports e router". |

---

## 5. Schema do banco

Migration `004_model_invocations.sql`:

```sql
CREATE TABLE model_invocations (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    skill_invocation_id BIGINT REFERENCES skill_invocations(id) ON DELETE SET NULL,

    provider TEXT NOT NULL,           -- 'anthropic' | 'openai' | 'openrouter' | 'ollama'
    model TEXT NOT NULL,              -- 'claude-sonnet-4-7' | 'qwen2.5:32b' | 'gpt-4o' etc.
    model_alias TEXT,                 -- string original ('anthropic:claude-sonnet-4-7') pra debug

    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,

    cost_usd NUMERIC(10, 6) NOT NULL DEFAULT 0,  -- ollama = 0
    latency_ms INTEGER NOT NULL,

    success BOOLEAN NOT NULL DEFAULT FALSE,
    error_kind TEXT,                  -- 'rate_limit' | 'timeout' | 'invalid_response' | 'auth' | etc.
    fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    fallback_from TEXT,               -- modelo original quando caiu pra fallback

    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX idx_model_invocations_provider_model ON model_invocations(provider, model, started_at DESC);
CREATE INDEX idx_model_invocations_session ON model_invocations(session_id);
CREATE INDEX idx_model_invocations_skill ON model_invocations(skill_invocation_id);
CREATE INDEX idx_model_invocations_cost ON model_invocations(cost_usd) WHERE cost_usd > 0;
```

Isso te dá, no SQL puro:

- "Qual skill consumiu mais USD essa semana?"
- "Qual modelo tem maior taxa de fallback?"
- "Latência p95 do Qwen local vs Claude Sonnet?"

Insumo direto pro dashboard que vai aparecer na Fase 7 e pra reflexão da Fase 8.

---

## 6. Formato da string `provider:model`

Padrão único pra toda config, CLI, manifest de skill, env var:

```
<provider>:<model_id>[:<tag>]
```

Exemplos válidos:

| String | Resolve em |
|---|---|
| `anthropic:claude-sonnet-4-7` | Anthropic API, modelo `claude-sonnet-4-7` |
| `anthropic:claude-opus-4-7` | Anthropic API, modelo `claude-opus-4-7` |
| `openai:gpt-4o` | OpenAI API, modelo `gpt-4o` |
| `openai:gpt-4o-mini` | OpenAI API, modelo `gpt-4o-mini` |
| `openrouter:anthropic/claude-3.5-sonnet` | OpenRouter, modelo `anthropic/claude-3.5-sonnet` |
| `openrouter:deepseek/deepseek-chat` | OpenRouter, modelo `deepseek/deepseek-chat` |
| `ollama:qwen2.5:32b` | Ollama local, modelo `qwen2.5:32b` (note os 2 `:`) |
| `ollama:llama3.3:70b` | Ollama local, modelo `llama3.3:70b` |
| `ollama:hermes3:8b` | Ollama local, Hermes 3 8B |
| `ollama:deepseek-r1:14b` | Ollama local, DeepSeek R1 14B |

Regex de validação no `schema.py`:

```python
MODEL_RE = re.compile(r"^(anthropic|openai|openrouter|ollama):[\w./\-]+(:[\w.\-]+)?$")
```

Parser:

```python
def parse_model_string(s: str) -> tuple[str, str]:
    """'ollama:qwen2.5:32b' → ('ollama', 'qwen2.5:32b')"""
    provider, _, model = s.partition(":")
    if not provider or not model:
        raise ValueError(f"Invalid model string: {s!r}")
    if provider not in {"anthropic", "openai", "openrouter", "ollama"}:
        raise ValueError(f"Unknown provider: {provider!r}")
    return provider, model
```

---

## 7. Capabilities — quem faz o quê

Nem todo modelo aceita tool use. Nem todo aceita imagens. O router precisa saber antes de tentar.

```python
@dataclass(frozen=True)
class Capabilities:
    tool_use: bool          # function calling nativo
    vision: bool            # aceita imagens no input
    json_mode: bool         # garante JSON válido na saída
    streaming: bool
    max_context: int        # tokens
    parallel_tools: bool    # pode chamar múltiplas tools no mesmo turno
```

Tabela base (`core/models/capabilities.py`):

| Provider | Modelo | tool_use | vision | json_mode | max_context |
|---|---|---|---|---|---|
| anthropic | claude-sonnet-4-7 | ✅ | ✅ | ✅ | 200k |
| anthropic | claude-opus-4-7 | ✅ | ✅ | ✅ | 200k |
| anthropic | claude-haiku-4-5 | ✅ | ✅ | ✅ | 200k |
| openai | gpt-4o | ✅ | ✅ | ✅ | 128k |
| openai | gpt-4o-mini | ✅ | ✅ | ✅ | 128k |
| openrouter | anthropic/claude-3.5-sonnet | ✅ | ✅ | ✅ | 200k |
| openrouter | deepseek/deepseek-chat | ✅ | ❌ | ✅ | 64k |
| ollama | qwen2.5:* | ✅ | ❌ | ✅ | 32k |
| ollama | llama3.3:* | ✅ | ❌ | ✅ | 128k |
| ollama | hermes3:* | ✅ | ❌ | ✅ | 128k |
| ollama | deepseek-r1:* | ❌ (reasoning model) | ❌ | ❌ | 128k |
| ollama | gemma2:* | ❌ | ❌ | ❌ | 8k |

Pra Ollama em geral, descoberta dinâmica via `GET /api/show` (que retorna `capabilities` no payload em versões recentes), com fallback pra tabela hardcoded por família de modelo.

**Regra:** se a skill exige `tool_use=True` e o modelo escolhido não tem, o router **falha cedo com mensagem clara** — não tenta executar e dar pau no meio.

---

## 8. Ollama — onde roda

Você tem 3 opções, todas suportadas:

### Opção A — Ollama na mesma máquina (recomendado pra dev)

```bash
# instala
curl -fsSL https://ollama.com/install.sh | sh

# puxa um modelo
ollama pull qwen2.5:7b
ollama pull hermes3:8b

# valida
curl http://localhost:11434/api/tags
```

`.env`:
```
OLLAMA_BASE_URL=http://localhost:11434
```

### Opção B — Ollama em container separado (recomendado pra prod/VPS)

Adiciona ao `docker-compose.yml`:

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: unless-stopped

volumes:
  ollama_data:
```

`.env`:
```
OLLAMA_BASE_URL=http://ollama:11434
```

Sem GPU, remova o bloco `deploy` — vai rodar em CPU (lento mas funciona pra modelos pequenos tipo `qwen2.5:7b`, `phi4:mini`).

### Opção C — Ollama em outra máquina

```
OLLAMA_BASE_URL=http://192.168.1.50:11434
```

O Transport não liga, é só HTTP.

**Pra Fase 4, escolha a Opção A.** Container vem na Fase 11 (deploy).

---

## 9. Fallback chain

Por padrão, **desligado**. Cair pra cloud sem você saber é como deixar a torneira pingando dinheiro.

Quando ligado (`MODEL_FALLBACK_CHAIN` no `.env`):

```
MODEL_FALLBACK_CHAIN=ollama:qwen2.5:32b,anthropic:claude-haiku-4-5,anthropic:claude-sonnet-4-7
```

Comportamento:

1. Skill pede `ollama:qwen2.5:32b`. Tenta.
2. Health check falha (Ollama down) OU chamada estoura `MODEL_TIMEOUT_S`. Loga erro.
3. Vai pro próximo da chain: `anthropic:claude-haiku-4-5`. Tenta.
4. Se passar, registra `fallback_used=true, fallback_from='ollama:qwen2.5:32b'` em `model_invocations`.
5. Se falhar tudo, retorna erro pro chamador.

Importante:

- Fallback **só** dispara em erro de infra (timeout, 5xx, conexão). Erro de validação ou rate limit 429 **não** pula — esses são erros de uso, não de disponibilidade.
- Cada degrau do fallback respeita as capabilities da skill. Se a skill exige tool use e o próximo modelo não tem, pula esse degrau.
- Tem `MAX_FALLBACK_DEPTH=2` (default) pra não cair em cascata infinita.

---

## 10. Interface CLI

Comandos novos em `core/cli.py`:

```bash
# Lista todos os modelos disponíveis (cloud hardcoded + ollama via /api/tags)
agent model list
# Saída:
# PROVIDER     MODEL                              CTX     TOOL   VISION   COST_IN   COST_OUT
# anthropic    claude-sonnet-4-7                  200k    ✓      ✓        $3.00     $15.00
# anthropic    claude-opus-4-7                    200k    ✓      ✓        $15.00    $75.00
# openai       gpt-4o                             128k    ✓      ✓        $2.50     $10.00
# ollama       qwen2.5:32b                        32k     ✓      ✗        $0        $0
# ollama       hermes3:8b                         128k    ✓      ✗        $0        $0

# Detalhes de um modelo
agent model show ollama:qwen2.5:32b

# Health check de todos os providers configurados
agent model health
# Saída:
# anthropic    ✓ ok (148ms)
# openai       ✗ no API key configured
# ollama       ✓ ok (8ms) — 4 models loaded

# Teste rápido de um modelo (manda "ping" e mostra resposta + latência + custo)
agent model test ollama:qwen2.5:32b

# Run com modelo override
agent run "resume isso aí" --model ollama:qwen2.5:32b
agent run "explica esse traceback" --model anthropic:claude-opus-4-7

# Skill run com modelo override
agent skill run summarize_text --arg text="..." --model ollama:hermes3:8b

# Ver gastos do dia
agent model costs --since today
# Saída:
# MODEL                                CALLS   TOKENS    COST_USD
# anthropic:claude-sonnet-4-7          47      82,341    $0.47
# anthropic:claude-haiku-4-5           12      8,210     $0.01
# ollama:qwen2.5:32b                   89      203,442   $0
# TOTAL                                148                $0.48
```

---

## 11. Como skills consomem isso

A Fase 3 já reservou o campo `model:` no manifest. Esta fase finalmente honra ele.

```yaml
# core/skills/builtin/summarize_text.md
---
name: summarize_text
description: Resume um texto em N bullets.
version: 2
model: ollama:qwen2.5:7b   # ← agora funciona de verdade
arguments:
  - name: text
    type: str
    required: true
  - name: count
    type: int
    default: 5
tags: [text, util]
---

Resuma o texto a seguir em {{ count }} bullets curtos, em português.

Texto:
{{ text }}
```

Resolução de modelo no `runner.py`, em ordem de prioridade:

1. Argumento explícito da chamada (`agent skill run X --model ...`)
2. Campo `model:` do manifest da skill
3. Variável de ambiente `DEFAULT_MODEL`
4. Hardcoded fallback final: `anthropic:claude-sonnet-4-7`

Cada degrau valida que o modelo existe e tem as capabilities exigidas pela skill (skill que tem `requires_tools: true` no manifest precisa de `tool_use`).

---

## 12. Streaming

Todos os 4 transports implementam streaming via async generator:

```python
async def stream(self, ...) -> AsyncIterator[StreamChunk]:
    yield StreamChunk(type="text_delta", text="...")
    yield StreamChunk(type="tool_use_start", tool_name="...", tool_id="...")
    yield StreamChunk(type="tool_use_input", partial_json="...")
    yield StreamChunk(type="tool_use_end")
    yield StreamChunk(type="message_end", usage=Usage(...))
```

Cada Transport converte do formato proprietário (Anthropic SSE, OpenAI SSE, Ollama NDJSON) pra esse formato unificado. Na Fase 4 a CLI **não** usa streaming (continua síncrono pra simplicidade); é a base pra Fase 7 (UI) consumir.

---

## 13. Custo — como é calculado

`core/models/pricing.py` mantém uma tabela:

```python
PRICING_USD_PER_1M = {
    "anthropic:claude-sonnet-4-7": (3.00, 15.00),    # (input, output)
    "anthropic:claude-opus-4-7":   (15.00, 75.00),
    "anthropic:claude-haiku-4-5":  (0.80, 4.00),
    "openai:gpt-4o":               (2.50, 10.00),
    "openai:gpt-4o-mini":          (0.15, 0.60),
    # OpenRouter: usa o pricing da rota (vem na response)
    # Ollama: zero
}

def cost_usd(model_alias: str, input_tokens: int, output_tokens: int) -> Decimal:
    if model_alias.startswith("ollama:"):
        return Decimal("0")
    if model_alias.startswith("openrouter:"):
        # OpenRouter retorna 'usage.cost' no response. Usar isso direto.
        ...
    rates = PRICING_USD_PER_1M.get(model_alias)
    if not rates:
        return Decimal("0")  # modelo desconhecido, não chuta
    in_rate, out_rate = rates
    return (
        Decimal(input_tokens)  * Decimal(str(in_rate))  / Decimal("1_000_000") +
        Decimal(output_tokens) * Decimal(str(out_rate)) / Decimal("1_000_000")
    )
```

Anthropic e OpenAI retornam `usage.input_tokens` e `usage.output_tokens` direto. Ollama retorna `prompt_eval_count` e `eval_count` — mapear pra input/output. Custo é gravado em `cost_usd` na migration.

---

## 14. Testes

### Unitários (não dependem de API real)

| Arquivo | O que testa |
|---|---|
| `test_router.py` | Parsing de string, resolução pra Transport correto, fallback chain (com mocks de health), capability check |
| `test_anthropic.py` | Conversão Message ↔ Anthropic format, parsing de tool calls, parsing de usage |
| `test_openai.py` | Idem pra OpenAI |
| `test_openrouter.py` | Idem + headers obrigatórios (HTTP-Referer, X-Title) |
| `test_ollama.py` | Idem + descoberta de capabilities via `/api/show` |
| `test_pricing.py` | Cálculo de custo nos providers, ollama=0, openrouter usa usage.cost |

Use `respx` ou `httpx.MockTransport` pra mockar HTTP.

### Integração (opcionais, marcados)

`tests/integration/test_real_ollama.py`:

```python
@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OLLAMA_BASE_URL"), reason="Ollama not configured")
async def test_real_ollama_chat():
    transport = OllamaTransport(base_url=os.environ["OLLAMA_BASE_URL"])
    health = await transport.health()
    if not health.ok:
        pytest.skip("Ollama not responding")
    resp = await transport.chat(
        messages=[Message(role="user", content="Say 'ping' and nothing else.")],
        model="qwen2.5:7b",
    )
    assert "ping" in resp.text.lower()
```

Roda com `pytest -m integration` quando você quer testar de verdade. CI normal pula.

### Critérios de aceitação

- [ ] `agent model list` lista pelo menos Anthropic + Ollama (com modelos que você tiver puxado).
- [ ] `agent model health` mostra status de cada provider configurado.
- [ ] `agent model test anthropic:claude-haiku-4-5` retorna resposta + latência + custo.
- [ ] `agent model test ollama:qwen2.5:7b` retorna resposta + latência + `cost_usd=0`.
- [ ] `agent run "ping" --model ollama:qwen2.5:7b` funciona sem chamar Anthropic.
- [ ] `agent run "ping" --model anthropic:claude-haiku-4-5` funciona sem precisar de Ollama.
- [ ] Skill builtin com `model: ollama:qwen2.5:7b` no manifest é executada localmente.
- [ ] Skill builtin com `model: anthropic:claude-haiku-4-5` é executada na cloud.
- [ ] Tabela `model_invocations` tem 1 linha por chamada, com `cost_usd` correto.
- [ ] Skill que exige tool use + modelo sem tool use → erro claro **antes** de chamar API.
- [ ] Fallback chain funciona quando Ollama está parado e chain está configurada.
- [ ] Fallback chain **não** dispara em rate limit (erro 429).
- [ ] `agent model costs --since today` soma certo.
- [ ] Todos os testes unitários passando (`pytest tests/models`).
- [ ] `docker compose up -d` continua subindo limpo (com a migration nova aplicada).
- [ ] `CLAUDE.md` atualizado com nova seção "Multi-modelo" e exemplos.

---

## 15. Riscos e como cada um é endereçado

| Risco | Mitigação |
|---|---|
| Ollama não tem todas as features que cloud tem | Capabilities flag por modelo, router rejeita cedo. |
| Tool use no Ollama é instável em alguns modelos | Tabela de capabilities tem boolean `tool_use` por família. Modelos sem suporte falham antes de chamar. |
| Modelo Ollama não puxado retorna 404 | Transport detecta, retorna erro tipado `ModelNotPulled`, mensagem da CLI sugere `ollama pull X`. |
| OpenRouter mudou cabeçalhos obrigatórios | Headers configurados em `OPENROUTER_HTTP_REFERER` e `OPENROUTER_X_TITLE` no `.env`. |
| Streaming inconsistente entre providers | `StreamChunk` é o protocolo unificado. Cada Transport adapta. |
| Pricing fica desatualizado | `pricing.py` tem comentário com data de last update; teste falha se modelo conhecido sem pricing. |
| Fallback silencioso queima dinheiro | `fallback_used=true` é flag explícita no banco. Comando `agent model costs` mostra fallbacks separados. CLI loga warn quando cai. |
| Embeddings da Fase 2 dependem de qual modelo? | **Não mexer**. Embeddings ficam só no provider que já estava configurado (Anthropic ou local sentence-transformers). Esta fase é só pro modelo de chat. |
| Migration nova quebra Postgres existente | Migration 004 só `CREATE TABLE`, não toca em existentes. Idempotente com `IF NOT EXISTS`. |
| Mock de Ollama no teste diverge do real | Teste `@pytest.mark.integration` valida contra Ollama de verdade quando disponível. |
| Transport vaza chave de API em log | Logger filtra `Authorization`, `x-api-key`, `OPENROUTER_API_KEY` no formatter. |

---

## 16. O que NÃO é Fase 4 (deixa pra depois)

- ❌ **Auto-router treinado** (escolhe modelo automaticamente baseado no tipo de tarefa). Fica pra Fase 8 (reflexão pode sugerir, mas a decisão continua declarativa).
- ❌ **Caching de respostas idênticas**. Fase 8 ou 10.
- ❌ **Roteamento por orçamento** ("se já gastei $X hoje, cai pra modelo barato"). Fase 8.
- ❌ **Embeddings multi-provider** (esta fase é só chat). Fase 10 se precisar.
- ❌ **Vision/imagens no input**. Capabilities estão expostos, mas o agente ainda não envia imagens — fica pra Fase 7 (UI).
- ❌ **Function calling streaming partial JSON**. Streaming entrega o tool call inteiro no `tool_use_end`. Parsing parcial fica pra Fase 7.
- ❌ **Suporte a Bedrock, Vertex, Azure OpenAI**. Adicionar depois é só novo Transport — a abstração já suporta.

Mantenha disciplina. Se o Claude Code propor mais que isso, recuse.

---

## 17. Passo a passo de execução (pra você seguir)

### Passo 0 — Confirme que a Fase 3 está sã

```bash
cd ~/Desktop/agent
docker compose ps              # postgres up
agent skill list                # ≥4 builtins
agent skill run summarize_text --arg text="texto longo de teste" --arg count=3
docker compose exec postgres psql -U agent -d agent -c "SELECT count(*) FROM skill_invocations;"
```

Se algum desses falhar, **pare** e conserte a Fase 3 antes.

### Passo 1 — Salve o spec

```bash
mkdir -p docs/phases
# salva este arquivo em docs/phases/phase-4-spec.md
```

### Passo 2 — Atualize o `.env`

```bash
cp .env .env.bak.fase3

# adiciona ao .env (não substitui o que já tem)
cat >> .env <<'EOF'

# ---- Fase 4: Multi-modelo ----
DEFAULT_MODEL=anthropic:claude-sonnet-4-7
MODEL_TIMEOUT_S=60
MODEL_FALLBACK_CHAIN=

# Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434

# OpenAI (opcional — deixa vazio se não tiver)
OPENAI_API_KEY=

# OpenRouter (opcional)
OPENROUTER_API_KEY=
OPENROUTER_HTTP_REFERER=https://github.com/seu-usuario/seu-repo
OPENROUTER_X_TITLE=meu-agente
EOF
```

### Passo 3 — Instale Ollama e puxe ao menos um modelo pequeno

```bash
# Linux/Mac
curl -fsSL https://ollama.com/install.sh | sh

# valida
ollama --version
ollama pull qwen2.5:7b   # ~4.7GB, roda em CPU se necessário
ollama list
curl http://localhost:11434/api/tags  # tem que retornar JSON com qwen2.5:7b
```

Se você tem GPU e quer um modelo melhor pra teste:

```bash
ollama pull qwen2.5:32b      # ~20GB, precisa de ~24GB VRAM ou rodar quantizado
# ou
ollama pull hermes3:8b       # ~5GB, ótimo pra tool use
```

### Passo 4 — Sanity check do Postgres

```bash
docker compose exec postgres psql -U agent -d agent -c "\dt"
# Tem que listar: sessions, messages, memories, skill_invocations
# A migration 004 vai adicionar model_invocations — confere que ainda NÃO existe
```

### Passo 5 — Abra o Claude Code

```bash
docker compose down   # derruba antes
claude
```

Sessão **nova**. Não emende com a Fase 3.

### Passo 6 — Primeira mensagem (cole exatamente)

```
Leia CLAUDE.md e docs/phases/phase-4-spec.md.

Antes de codar, me dê o plano detalhado pra executar a Fase 4 — Multi-modelo. Quero ver:
1. Ordem dos arquivos que você vai criar/editar
2. Quais dependências você vai adicionar no pyproject.toml (versão exata)
3. Como você vai refatorar o código atual da Fase 1 que chama Anthropic direto pro novo ModelRouter — sem quebrar a Fase 3
4. Como vai mockar HTTP nos testes (respx? httpx.MockTransport?)
5. Como vai descobrir capabilities do Ollama (via /api/show ou tabela hardcoded?)
6. Como o fallback chain vai detectar "infra error" vs "user error" pra decidir se pula
7. Quais skills builtin existentes você vai mudar pra ter o campo `model:` apontando pra Ollama
8. Como vai garantir que a migration 004 é idempotente
9. Pontos onde você pretende me pedir confirmação

Não escreva código ainda.
```

Vai devolver o plano. 1-2 minutos.

### Passo 7 — Revise o plano

Pontos críticos pra checar:

- [ ] Ele entendeu que o `AnthropicTransport` é **refator** (não reescrita) do que já existe.
- [ ] Ele vai usar a **mesma interface** do `Transport` Protocol pra todos os 4 providers.
- [ ] Ele vai criar `core/models/transports/openrouter.py` herdando de `OpenAITransport` (não duplicando código).
- [ ] Ele vai mockar HTTP nos testes (sem chamar API real no CI).
- [ ] Ele vai aplicar a migration 004 dentro do container Postgres, não só criar o arquivo.
- [ ] Ele vai validar capabilities **antes** de chamar API, falhando cedo.
- [ ] Ele entendeu que `MODEL_FALLBACK_CHAIN` vazio = sem fallback (default seguro).
- [ ] Ele **não** vai mexer em embeddings/pgvector da Fase 2.
- [ ] Ele **não** vai mexer no ciclo de match/promote de skills da Fase 3.
- [ ] Ele vai logar custo no banco mesmo pra Ollama (com 0).

Se algo estiver errado:

```
Antes de aprovar, ajusta esses pontos no plano:
1. [ponto X]
2. [ponto Y]
```

### Passo 8 — Aprove e deixe executar

```
Plano aprovado. Pode executar.

Me peça confirmação antes de:
- mexer em qualquer arquivo das Fases 1, 2 ou 3 que NÃO esteja na seção "Arquivos a modificar" do spec
- aplicar a migration 004 no Postgres
- adicionar dependências no pyproject.toml
- editar manifests de skill builtin existentes
```

Vai demorar 2-3h. Aprova `y` quando ele pedir.

### Passo 9 — Validação manual (você faz, NÃO o Claude Code)

Quando ele disser "Fase 4 concluída", **não acredite ainda**. Roda na mão:

```bash
# 1. Sobe banco
docker compose up -d postgres
docker compose exec postgres psql -U agent -d agent -c "\d model_invocations"
# Tem que existir e ter as colunas certas.

# 2. Lista modelos
agent model list

# 3. Health
agent model health

# 4. Testa Anthropic (cloud)
agent model test anthropic:claude-haiku-4-5

# 5. Testa Ollama (local)
agent model test ollama:qwen2.5:7b

# 6. Run normal com modelo override
agent run "diga 'pong' e nada mais" --model ollama:qwen2.5:7b
agent run "diga 'pong' e nada mais" --model anthropic:claude-haiku-4-5

# 7. Skill com model no manifest
agent skill show summarize_text   # confere que tem `model: ollama:...`
agent skill run summarize_text --arg text="texto longo aqui" --arg count=3

# 8. Verifica registros no banco
docker compose exec postgres psql -U agent -d agent -c \
  "SELECT provider, model, input_tokens, output_tokens, cost_usd, latency_ms, success FROM model_invocations ORDER BY started_at DESC LIMIT 10;"

# 9. Custos
agent model costs --since today

# 10. Teste de fallback (com Ollama parado)
sudo systemctl stop ollama   # ou para o container
# adiciona MODEL_FALLBACK_CHAIN=ollama:qwen2.5:7b,anthropic:claude-haiku-4-5 no .env
agent run "ping" --model ollama:qwen2.5:7b
# Tem que cair pro Anthropic e logar fallback_used=true

# 11. Restart Ollama
sudo systemctl start ollama
```

Se algum dos 11 falhar, **não é Fase 4 concluída**. Volta pro Claude Code e descreve o que falhou.

### Passo 10 — Commit

```bash
git add .
git commit -m "feat(phase-4): multi-model transports (anthropic, openai, openrouter, ollama)"
git tag phase-4-done
```

---

## 18. Estimativa

- Sessão Claude Code: 2.5–3.5h, ~$2–4 USD.
- Você revisando + validando: 1–1.5h.
- Total wall-clock: meio dia se nada quebrar; 1 dia se Ollama der trabalho na primeira instalação.

---

## 19. Próxima fase

Fase 5 — **Gateway Node + Telegram**. Já com multi-modelo, o gateway pode rotear mensagens do Telegram pro agente, e o agente responde usando o modelo definido pela skill ativada. É a primeira fase em que outra pessoa (você no celular) interage com o agente sem CLI.
