# Ollama Cloud

A EVE suporta tanto **Ollama local** (`http://localhost:11434`) quanto **Ollama Cloud** (`https://ollama.com`) através do mesmo `OllamaTransport`.

## Quando usar Ollama Cloud?

| Cenário | Recomendação |
|---------|--------------|
| Você tem GPU local potente (12+ GB VRAM) | **Local** — sem custo recorrente |
| Sem GPU ou GPU fraca | **Cloud** — modelos grandes (120B+) acessíveis |
| Privacidade total dos dados | **Local** — nada sai da sua máquina |
| Deploy em VPS sem GPU | **Cloud** — ideal |
| Prototipagem rápida | **Cloud** — zero setup |
| Custo otimizado em volume alto | **Local** — sem cobrança por token |

## Configuração

### 1. Obter API key

1. Acesse https://ollama.com/settings/keys
2. Faça login (criação de conta gratuita)
3. Crie uma nova API key
4. Copie a chave (formato `ollama_...`)

### 2. Configurar `.env`

```bash
# Aponta para a cloud em vez do localhost
OLLAMA_BASE_URL=https://ollama.com

# Sua API key da cloud
OLLAMA_API_KEY=ollama_sua_chave_aqui

# Modelo padrão (use modelos cloud-only para máximo proveito)
DEFAULT_MODEL=ollama:gpt-oss:120b
```

### 3. Reiniciar o Core

```bash
docker compose restart core
```

### 4. Validar

```bash
agent model health
# Deve mostrar: ollama → ok (latência ~X ms)

agent model test ollama:gpt-oss:120b "Oi, tudo bem?"
```

## Modelos disponíveis na Cloud

| Modelo | Tamanho | Uso recomendado |
|--------|---------|-----------------|
| `gpt-oss:120b` | 120B | Tarefas complexas, raciocínio profundo |
| `qwen3-coder:480b-cloud` | 480B | Geração de código avançada |
| `deepseek-v3.1:671b-cloud` | 671B | Estado-da-arte, missões críticas |
| `kimi-k2:1t-cloud` | 1T | Maior modelo disponível |

> Lista atualizada em: https://ollama.com/library

## Usando local e cloud ao mesmo tempo

Você pode configurar fallback chain mista:

```bash
DEFAULT_MODEL=ollama:gpt-oss:120b
MODEL_FALLBACK_CHAIN=anthropic:claude-haiku-4-5,ollama:qwen2.5:7b
```

Se a Cloud falhar (timeout, 5xx), cai para Claude. Se Claude falhar, cai para Ollama local.

## Custos

A Ollama Cloud cobra por consumo. Veja https://ollama.com/pricing.

A EVE registra **todo custo** automaticamente em `model_invocations`:

```bash
agent model costs --since today
# Mostra gastos por provider/modelo
```

## Segurança

⚠️ **A API key é uma credencial crítica.** Trate como senha:

- ✅ Use `.env` (já está no `.gitignore`)
- ✅ Em produção, use secrets manager (Vault, AWS Secrets Manager, etc.)
- ✅ Rotacione periodicamente
- ❌ NUNCA comite em código
- ❌ NUNCA envie em logs (o transport já não loga a key)

## Troubleshooting

### `PermissionError: OLLAMA_API_KEY`

A chave é inválida ou expirou. Gere uma nova em https://ollama.com/settings/keys.

### `ModelNotPulledError: gpt-oss:120b`

O modelo não está disponível na sua conta/região. Verifique a lista em https://ollama.com/library.

### Timeouts frequentes

Aumente o timeout:

```bash
# .env
MODEL_TIMEOUT_S=180   # 3 minutos para modelos grandes
```

Ou na config:

```yaml
# config/config.yaml
providers:
  ollama:
    timeout: 180
```

### Latência alta

Modelos cloud têm latência inerente (~2-10s por resposta). Para tarefas onde latência importa, considere:

- Usar modelo menor (`gpt-oss:120b` em vez de `kimi-k2:1t-cloud`)
- Fallback chain: começar pelo Claude Haiku, cair para Ollama Cloud só se necessário

## Detecção automática

O transport detecta se está em modo cloud pela presença de `api_key`:

```python
from agent.config import get_settings
from agent.models.transports.ollama import OllamaTransport

settings = get_settings()
transport = OllamaTransport(
    base_url=settings.ollama.base_url,
    api_key=settings.ollama.api_key,
)

print(transport.is_cloud)   # True se OLLAMA_API_KEY foi configurada
```

## Comparação API: local vs cloud

| Endpoint | Local | Cloud |
|----------|-------|-------|
| `POST /api/chat` | ✅ | ✅ |
| `POST /api/generate` | ✅ | ✅ |
| `GET /api/tags` | ✅ Modelos locais | ✅ Modelos disponíveis na cloud |
| `POST /api/show` | ✅ | ✅ |
| `POST /api/pull` | ✅ | ❌ Modelos cloud não precisam pull |
| Authorization header | Opcional | **Obrigatório** |

A EVE abstrai essas diferenças — o mesmo código funciona em ambos os modos.
