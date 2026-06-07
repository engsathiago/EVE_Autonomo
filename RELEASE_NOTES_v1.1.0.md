# EVE Autônomo — Release Notes v1.1.0

**Data:** 7 de junho de 2026
**Tag:** `v1.1.0`
**Commits desde v1.0.0:** ~46

---

## Visão geral

A v1.1.0 fecha três débitos fundamentais que a v1.0.0 deixou em aberto: o provedor de modelos padrão era Anthropic (dependência externa paga), o Critic existia mas nunca interceptava nada, e os testes das fases F5/F6/F7/F8/F9/F11 não tocavam Postgres real. Esta release corrige os três, e ainda estabelece o padrão de runtime validation que vai guiar todas as fases futuras.

---

## Mudança principal: Ollama Cloud como default

### O problema anterior

Até a v1.0.0, toda invocação LLM do agente — classificação de tier, planejamento de missão, crítico, reflexão — chamava `anthropic:claude-haiku-4-5` ou `anthropic:claude-sonnet-4-6` diretamente. Isso estava hardcoded em `TierClassifier`, `Critic`, `MissionPlanner` e `MissionReflector`. Qualquer instalação sem `ANTHROPIC_API_KEY` simplesmente falhava silenciosamente, ou caía no fallback de forma não intencional.

### O que mudou

O `ModelRouter` agora usa `ollama_cloud:deepseek-v3.1:cloud` como default. O `OllamaCloudTransport` foi criado como provider separado do `OllamaTransport` local — ele autentica via Bearer token (`OLLAMA_CLOUD_API_KEY`) e aponta para a API cloud do Ollama, não para `localhost:11434`.

Cada componente LLM ganhou seu próprio setting configurável:

```yaml
# config.yaml
orchestrator:
  classifier_model: ollama_cloud:gpt-oss:20b-cloud

critic:
  medium_model: ollama_cloud:gpt-oss:20b-cloud
  primary_model: ollama_cloud:kimi-k2.5:cloud

missions:
  planner_model: ollama_cloud:gpt-oss:20b-cloud
  reflector_model: ollama_cloud:kimi-k2.5:cloud
```

### Como reverter para Anthropic

Se você prefere usar Anthropic como provider principal, basta setar no `.env`:

```bash
DEFAULT_MODEL=anthropic:claude-sonnet-4-6
MODEL_FALLBACK_CHAIN=
```

E ajustar os modelos por componente no `config.yaml` se quiser granularidade. O Anthropic continua suportado — apenas deixou de ser o default obrigatório.

---

## Critic finalmente operacional

### O problema (KI-1)

A Fase 7 implementou o `Critic` com 3 personas (técnico, advogado do diabo, sintetizador) e integrou a `ReflexiveMemory`. O código estava correto, os testes unitários passavam. Mas havia um problema silencioso: o `AIAgent._execute_tools()` nunca chamava `needs_critic()`. O Critic era registrado, aparecia no status, mas nunca era invocado durante a execução real de tools.

O resultado: skills marcadas como `irreversible=True` (envio de e-mail, operações de filesystem destrutivas, chamadas a APIs externas) eram executadas sem passar pelo gate do Critic.

### O que mudou

O `AIAgent._execute_tools()` agora chama `needs_critic()` antes de executar qualquer tool marcada como irreversível. Se o Critic retorna `verdict=REJECT` ou `verdict=ESCALATE`, a tool não é executada e a missão recebe status `blocked_by_critic`.

A migration `017_blocked_by_critic.sql` adiciona o novo status à enum da tabela `missions` e cria índice parcial em `critic_evaluations(mission_id)` para buscas eficientes no histórico de avaliações.

Adicionalmente, `Settings.from_yaml()` agora parseia corretamente o bloco `critic:` do `config.yaml` — antes esse bloco era lido mas os valores eram descartados, fazendo o Critic sempre usar defaults internos.

---

## Runtime validation: do mock para a realidade

### O gap descoberto

A auditoria de maio/2026 revelou um padrão preocupante: o CHANGELOG dizia "1158 testes passando" para F0–F13, mas a maioria desses testes mocava o banco, mocava o Redis, mocava o LLM. Eles validavam a lógica interna do código, mas não o comportamento real do sistema rodando.

Quando a Sub-fase D.5 tentou fazer runtime testing das fases mais antigas (F5, F6, F7), vários bugs surgiram imediatamente:

- **F5 (ApprovalManager):** asyncpg recusava `dict` Python direto em colunas `jsonb`. O código de production sempre convertia via `json.dumps`, mas nenhum teste tocava o Postgres real para detectar isso.
- **F11 (Web UI):** o endpoint `POST /api/ui/chat` não existe — chat só funciona via WebSocket. Havia documentação interna descrevendo o endpoint, mas nenhum teste de integração que exercitasse a rota real.

### Como a Sub-fase C resolveu

Foi criado um framework de runtime validation com três componentes:

1. **Marker `runtime`** no `pyproject.toml` — testes marcados com `@pytest.mark.runtime` são ignorados no CI normal (que não tem Postgres) e executados separadamente com `pytest -m runtime`.

2. **Fixture asyncpg pattern** — conexão direta ao Postgres real via asyncpg, sem ORM, sem mock. Qualquer comportamento de serialização/deserialização de dados é testado contra o banco real.

3. **Evidence files** — cada teste runtime bem-sucedido grava um arquivo em `tests/runtime/evidence/` com o ID do artefato criado (approval ID, cron job ID, etc.). Esse arquivo funciona como prova auditável de que o teste passou contra um banco real.

Os 18 testes runtime agora cobrem:
- F5: criação e decisão de approval com asyncpg real
- F6: criação de cron job e subagente via APScheduler real
- F7: avaliação Critic e criação de missão com pgvector real
- F8: execução de sandbox (subprocess + Docker)
- F9: síntese e promoção de skill com embeddings reais
- F11: WebSocket multiplexado e autenticação token

Ver `docs/RUNTIME_TESTING.md` para o guia completo do padrão.

---

## Bugs corrigidos

### BUG_F5-A — jsonb serialization no ApprovalManager

**Sintoma:** `asyncpg.exceptions.DataError: invalid input for query argument $N: expected str, not dict`

**Causa:** `ApprovalManager.create()` passava `skill_args` (dict Python) e `channel_ref` (dict Python) diretamente para a query asyncpg. O asyncpg não serializa dicts automaticamente para jsonb — exige string JSON.

**Correção:** `json.dumps()` aplicado antes do INSERT. `json.loads()` aplicado ao ler de volta, via helper `_row_to_state()`.

### BUG_F5-B — UUID e jsonb deserialization no ApprovalManager

**Sintoma:** `pydantic.ValidationError: value is not a valid UUID` + `str is not a valid dict`

**Causa:** asyncpg retorna `UUID` como objeto Python `uuid.UUID` e campos jsonb como string JSON, não como dict. O construtor `ApprovalState` do Pydantic esperava `str` para o UUID e `dict` para os campos jsonb.

**Correção:** helper `_row_to_state()` que converte `uuid.UUID → str` e chama `json.loads()` nos campos jsonb antes de construir o `ApprovalState`.

---

## Gaps conhecidos

### GAP-F11-A — chat via WebSocket, não REST

O painel de chat do Web UI usa WebSocket (`ws://host/api/v1/stream`) com operação `chat.send`. Não existe endpoint REST `POST /api/ui/chat`. Documentação interna que descrevia esse endpoint estava incorreta — corrigida nesta release.

### GAP-F11-B — web_sessions não persiste

A tabela `web_sessions` (migration 012) existe no schema PostgreSQL, mas o código nunca executa INSERT. Sessions do WebSocket vivem em memória no dict `_WsSession`. Isso significa que um restart do processo invalida todas as sessions ativas. A persistência real de sessions WebSocket é trabalho para v1.2.

### F12 e F13 — código existe, runtime validation adiada

Os adaptadores de Discord, Slack e Email (F12) e o pipeline LoRA (F13) têm código implementado e testes unitários passando. Runtime validation com serviços reais (Discord API, servidor SMTP, GPU para LoRA) foi adiada para v1.2 por falta de ambiente de test adequado.

---

## Próximos passos

1. **VPS rebuild com `install_vps.sh`** — o script é idempotente e pode ser rodado em produção. Consolida os dois venvs de `core/` em um único `.venv312`.

2. **F12 runtime validation** — testar `DiscordAdapter`, `SlackAdapter` e `EmailAdapter` com contas de test reais.

3. **F13 runtime validation** — testar pipeline LoRA com GPU (mesmo que small model no Colab).

4. **Fix GAP-F11-A e B** — adicionar endpoint REST `POST /api/ui/chat` como alias do WebSocket, e persistir sessions em `web_sessions`.

5. **Cobertura → 60%** — target definido em v1.0, ainda não atingido (atual: ~30%).

---

## Estatísticas da release

| Métrica | Valor |
|---------|-------|
| Commits desde v1.0.0 | ~46 |
| Testes runtime adicionados | 18 |
| Bugs corrigidos | 2 (F5-A, F5-B) |
| Issues fechadas (KI) | 2 (KI-1 Critic, KI-2 OllamaCloud) |
| Gaps documentados | 18 (DEPLOY_GAP.md + RUNTIME_VALIDATION_REPORT.md) |
| Migrations novas | 1 (017_blocked_by_critic.sql) |
| Documentos novos | 7 (AUDIT_REPORT, PLAN, DEPLOY_GAP, RUNTIME_VALIDATION_REPORT, BUG_F5_DISCOVERED, BUG_F11_DISCOVERED, SPRINT_2_REPORT) |
