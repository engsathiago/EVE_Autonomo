# Ollama Cloud

A EVE suporta tanto **Ollama local** (provider `ollama`) quanto **Ollama Cloud** (provider `ollama_cloud`) como **providers separados**. Desde Sprint 2, `ollama_cloud` é o provider padrão.

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
# Provider Ollama Cloud (separado do provider "ollama" local)
OLLAMA_CLOUD_API_KEY=ollama_sua_chave_aqui
OLLAMA_CLOUD_BASE_URL=https://ollama.com   # padrão — só altere se necessário

# Modelo padrão (já configurado por default, só confirme)
DEFAULT_MODEL=ollama_cloud:deepseek-v3.1:cloud
```

### 3. Reiniciar o Core

```bash
docker compose restart core
```

### 4. Validar

```bash
agent model health
# Deve mostrar: ollama_cloud → ok (latência ~X ms)

agent model test ollama_cloud:deepseek-v3.1:cloud "Oi, tudo bem?"
```

## Modelos disponíveis na Cloud

| Modelo (string completa) | Tamanho | Uso recomendado |
|--------------------------|---------|-----------------|
| `ollama_cloud:gpt-oss:20b-cloud` | 20B | Classificação, planning (rápido) |
| `ollama_cloud:deepseek-v3.1:cloud` | ~70B | Default geral, reasoning |
| `ollama_cloud:kimi-k2.5:cloud` | — | Reflector, Critic sintetizador |
| `ollama_cloud:qwen3-coder:480b-cloud` | 480B | Geração de código avançada |

> Lista completa e atualizada em: https://ollama.com/library

## Mapeamento tier → modelo padrão

| Componente | Modelo padrão | Override via env |
|---|---|---|
| ModelRouter (default) | `ollama_cloud:deepseek-v3.1:cloud` | `DEFAULT_MODEL` |
| TierClassifier | `ollama_cloud:gpt-oss:20b-cloud` | `ORCHESTRATOR_CLASSIFIER_MODEL` |
| MissionPlanner | `ollama_cloud:gpt-oss:20b-cloud` | `MISSIONS_PLANNER_MODEL` |
| MissionReflector | `ollama_cloud:kimi-k2.5:cloud` | `MISSIONS_REFLECTOR_MODEL` |
| Critic (técnico/DA) | `ollama_cloud:gpt-oss:20b-cloud` | `CRITIC__MEDIUM_MODEL` |
| Critic (sintetizador) | `ollama_cloud:kimi-k2.5:cloud` | `CRITIC__PRIMARY_MODEL` |

## Trocar o provider padrão

Para reverter para Anthropic:

```bash
# .env
DEFAULT_MODEL=anthropic:claude-sonnet-4-6
ORCHESTRATOR_CLASSIFIER_MODEL=anthropic:claude-haiku-4-5
MISSIONS_PLANNER_MODEL=anthropic:claude-haiku-4-5
MISSIONS_REFLECTOR_MODEL=anthropic:claude-sonnet-4-6
CRITIC__MEDIUM_MODEL=anthropic:claude-haiku-4-5
CRITIC__PRIMARY_MODEL=anthropic:claude-sonnet-4-6
```

Ou via CLI (só o DEFAULT_MODEL):

```bash
agent model set-default anthropic:claude-sonnet-4-6
```

## Usando local e cloud ao mesmo tempo

Configure fallback chain no `.env`:

```bash
DEFAULT_MODEL=ollama_cloud:deepseek-v3.1:cloud
MODEL_FALLBACK_CHAIN=anthropic:claude-sonnet-4-6
```

Se a Cloud falhar (timeout, 5xx), cai automaticamente para Anthropic.
Rate limit (429) e erros de autenticação **não disparam** fallback.

## Custos

A Ollama Cloud cobra por consumo. Veja https://ollama.com/pricing.

A EVE registra todo custo automaticamente em `model_invocations`:

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

### `ValueError: OllamaCloudTransport requer autenticação`

`OLLAMA_CLOUD_API_KEY` está vazia. Configure no `.env` e reinicie.

### `PermissionError` (401/403)

A chave é inválida ou expirou. Gere uma nova em https://ollama.com/settings/keys.

### `ModelNotPulledError`

O modelo não está disponível na sua conta/região. Verifique a lista em https://ollama.com/library.

### Timeouts frequentes

```bash
# .env
MODEL_TIMEOUT_S=180   # 3 minutos para modelos grandes
```

Ou no `config/config.yaml`:

```yaml
providers:
  ollama_cloud:
    timeout: 180
```

### Latência alta

Modelos cloud têm latência inerente (~2-10s). Para tarefas latência-sensitivas:
- Use modelo menor (`ollama_cloud:gpt-oss:20b-cloud`)
- Inverta o fallback: `DEFAULT_MODEL=anthropic:claude-haiku-4-5`, com cloud como backup

## Diferença entre `ollama` e `ollama_cloud`

| | `ollama` | `ollama_cloud` |
|---|---|---|
| URL padrão | `http://localhost:11434` | `https://ollama.com` |
| Autenticação | Opcional | **Obrigatória** (`OLLAMA_CLOUD_API_KEY`) |
| Classe Python | `OllamaTransport` | `OllamaCloudTransport` (subclasse) |
| Configuração | `OLLAMA_BASE_URL`, `OLLAMA_API_KEY` | `OLLAMA_CLOUD_BASE_URL`, `OLLAMA_CLOUD_API_KEY` |
| Registro no router | Sempre (sem key) | Só quando `OLLAMA_CLOUD_API_KEY` configurada |
