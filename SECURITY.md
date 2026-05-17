# Política de Segurança

## Reportando uma Vulnerabilidade

A segurança da EVE é uma prioridade. Se você encontrar uma vulnerabilidade, **não abra uma issue pública**.

### Como reportar

Envie um e-mail para **eng.sathiago@gmail.com** com:

1. Descrição da vulnerabilidade
2. Passos para reproduzir
3. Impacto potencial (e.g., RCE, exfiltração de dados, escalação de privilégio)
4. Possível mitigação (se conhecer)

Você receberá uma confirmação em até **72 horas**.

### Processo de resposta

| Fase | Prazo |
|------|-------|
| Confirmação do recebimento | 72h |
| Avaliação inicial e severidade | 7 dias |
| Patch desenvolvido e testado | 30 dias (crítico: 7 dias) |
| Disclosure coordenado | Após patch publicado |

---

## Threat Model

A EVE executa código arbitrário, conecta-se a APIs externas e processa mensagens de canais não confiáveis. Os principais riscos são:

### 1. Execução de código não-confiável

**Vetor:** Tool `shell`, sandbox, skills auto-geradas, fine-tuning.

**Mitigações implementadas:**
- Sandboxes Docker com timeout hard e políticas de rede restritas
- Blacklist de comandos shell (`rm -rf /`, `mkfs`, `dd`, etc.)
- Workspace paths restringem acesso ao filesystem
- Aprovações humanas obrigatórias para operações destrutivas
- Sub-agentes isolados por construção (sem acesso a memory_store)

### 2. Injection via canais externos

**Vetor:** Mensagens de Telegram, Discord, Slack, E-mail processadas pelo agente.

**Mitigações implementadas:**
- **Allowlists obrigatórias** em todos os canais (sem allowlist, adapter não sobe)
- Rate limiting por usuário e por canal
- Redação de segredos em logs
- Validação de remetente em E-mail (anti-spoofing)

### 3. Exfiltração de credenciais

**Vetor:** LLM expondo segredos via tool calls ou respostas.

**Mitigações implementadas:**
- Credenciais via env vars (nunca em arquivos commitados)
- Pre-commit hook com `gitleaks` bloqueando commits com secrets
- `.gitignore` cobrindo `.env*` e variações
- CI roda secret scanning em todo PR
- System prompts instruem o agente a nunca expor credenciais

### 4. Custo descontrolado de API

**Vetor:** Loop infinito ou prompt malicioso explodindo consumo.

**Mitigações implementadas:**
- `max_iterations: 15` por goal
- `MAX_STEPS_PER_TICK: 3` no loop autônomo
- Tracking de custo por chamada em `model_invocations`
- Critic com `cost_threshold_usd` para invocação seletiva
- Fallback chain configurável (ex: cair para Ollama local)

### 5. Persistência de dados sensíveis em memória

**Vetor:** Curator persistindo PII em `memories` ou `reflexive_memory`.

**Mitigações implementadas:**
- Filtro PII no fine-tuning (email, CPF, telefone)
- Curator com modelo dedicado (Haiku) e prompt restritivo
- Capacidade de remover insights via API/CLI

### 6. Manipulação de modelos via fine-tuning

**Vetor:** Trace envenenado induzindo o modelo a comportamento malicioso.

**Mitigações implementadas:**
- Benchmark gates obrigatórios — checkpoint só ativa se score ≥ baseline
- Safety check com prompts adversariais
- Per-axis gate (nenhum eixo pode regredir > 5%)
- Ativação manual nas primeiras 5 rodadas
- Rollback atômico (`agent finetune rollback`)

---

## Boas Práticas para Operadores

### Em produção:
- ✅ Sempre defina allowlists explícitas para canais
- ✅ Use senhas fortes em `POSTGRES_PASSWORD`
- ✅ Mantenha o `.env` fora de version control
- ✅ Rotacione chaves API periodicamente
- ✅ Configure `ADMIN_USER_ID` para limitar aprovações
- ✅ Monitore `model_invocations` para detectar consumo anômalo
- ✅ Habilite HTTPS no web dashboard (use reverse proxy)
- ✅ Use Docker para isolamento (não rode como root no host)

### Nunca faça:
- ❌ Comitar arquivos `.env*` ou backups SQL
- ❌ Rodar o agente com `CHANNELS_ENABLED=*` sem allowlist
- ❌ Expor a porta 8000 diretamente na internet
- ❌ Permitir `requires_confirmation: false` em tools destrutivas
- ❌ Desabilitar o `Critic` em ambientes de produção
- ❌ Ativar checkpoint de fine-tuning sem benchmark aprovado

---

## Versões Suportadas

| Versão | Suporte |
|--------|---------|
| `main` | ✅ Suporte completo |
| Releases anteriores | ⚠️ Aplicar patches sob demanda |

Recomendamos sempre rodar a versão `main` ou a release mais recente.

---

## Reconhecimento

Pesquisadores de segurança que reportarem vulnerabilidades válidas seguindo o processo acima serão **publicamente reconhecidos** (com permissão) na seção de acknowledgments do `CHANGELOG.md` e no release notes.

Obrigado por ajudar a manter a EVE segura!
