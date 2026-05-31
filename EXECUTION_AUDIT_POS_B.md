# Re-validação F5–F13 pós Fase B + D.1

> Data: 2026-05-30
> Comparação: estado pré-B (todas TEÓRICAS) vs estado atual (pós D.1 + D.6)
> Método: smoke tests locais com DB real + inspeção de estrutura

---

## 1. Delta de contadores

| Tabela | Baseline | Final | Delta |
|---|---|---|---|
| skill_executions | 0 | 0 | 0 |
| subagent_runs | 9 | 9 | 0 |
| critic_evaluations | 9 | 9 | 0 |
| skill_invocations | 4 | 4 | 0 |
| channel_messages | 0 | 0 | 0 |
| mission_steps | 27 | 27 | 0 |
| sandbox_executions | 0 | 0 | 0 |
| model_invocations | 537 | 537 | 0 |
| missions | 13 | 13 | 0 |

**Delta total: zero em todas as tabelas.**
Motivo: smoke tests não ativaram LLM real (core Python offline durante testes, sem model_router wired). Os 9 subagent_runs e 537 model_invocations existentes são de sessões anteriores.

---

## 2. Veredito por fase

| Fase | Pré-B | Pós-D.1 | Evidência | Próxima ação |
|---|---|---|---|---|
| F5 | TEÓRICA | **PARCIAL** | 20 testes vitest passando; webhook 404; channel_messages delta=0 | Corrigir rota webhook; subir core junto |
| F6 | TEÓRICA | **PARCIAL** | SubagentPool importa; MissingRequiredTool OK; D.1 routing integrado; subagent_runs delta=0 | Rodar end-to-end com core+DB |
| F7 | TEÓRICA | **PARCIAL** | Critic importa; 3 personas (technical+devils_advocate+synthesizer); asyncio.gather confirmado; critic_evaluations delta=0 | Ver prompt D.4 (wiring no loop) |
| F8 | TEÓRICA | **PARCIAL** | SubprocessSandbox.run(['python3','-c','print(2+2)']) → exit_code=0, stdout='4'; sandbox_executions delta=0 | Conectar exec_tool ao DB log |
| F9 | TEÓRICA | **TEÓRICA** | SkillSynthesizer importa; skill_candidates=0; nenhuma skill auto-gerada; VoyagerGenerator não existe (B9) | Prompt 04 — refazer ciclo |
| F10 | TEÓRICA | **PARCIAL** | deploy/digitalocean/deploy.sh existe; docker-compose.yml válido; docker-compose.prod.yml ausente | Criar compose.prod separado |
| F11 | TEÓRICA | **PARCIAL** | webui/ com index.html+app.js+public/ existe; make_web_app() importa OK; sem rota raiz testada | Prompt 05 — wiring e servir estáticos |
| F12 | TEÓRICA | **TEÓRICA** | Python tem discord/slack/email adapters; gateway só tem canal telegram; sem rota para canais extras | Prompt 03 ou fase dedicada |
| F13 | TEÓRICA | **TEÓRICA** | agent/finetune/ existe (lora_trainer, checkpoint_gate etc.); finetune_runs=0; 0 invocações LoRA | Prompt 07 — rodar ciclo LoRA |

---

## 3. Bugs novos encontrados

Ver `BUGS_ENCONTRADOS_D5.md`. Resumo:
- **B1**: tabela `tool_executions` inexistente (nome real: `skill_executions`)
- **B2**: webhook `/webhook/telegram` → 404 (rota não registrada no gateway)
- **B3**: gateway health degraded (core offline durante smoke tests)
- **B4**: `SandboxExecutor`/`exec_tool` não existem; `SubprocessSandbox` existe mas não loga em DB
- **B5**: coluna `skills.auto_generated` não existe no schema atual
- **B6**: coluna `model_invocations.model_name` não existe (é `model`)
- **B7**: `docker-compose.prod.yml` ausente
- **B8**: `agent.web` não exporta `app` no `__init__.py`
- **B9**: `VoyagerSkillGenerator` não existe (módulo é `SkillSynthesizer`)

---

## 4. Conclusão honesta

- **0 fases VALIDADAS** — nenhuma produziu evidência DB nova
- **5 fases PARCIAIS** — F5, F6, F7, F8, F10, F11 (estrutura existe e importa, sem end-to-end com DB)
- **3 fases TEÓRICAS** — F9, F12, F13 (módulos existem mas sem ciclo funcional)
- **0 fases QUEBRADAS** — nenhuma regressão confirmada (testes unitários passam)

Ajuste: contando 6 PARCIAIS (F5, F6, F7, F8, F10, F11) + 3 TEÓRICAS (F9, F12, F13).

A causa raiz do delta zero: os smoke tests precisam do core Python rodando para
produzir evidência DB. Sem `agent.server` up (com pool postgres wired), SubagentPool,
Critic e Sandbox não persistem. Os módulos existem e importam — o sistema não está quebrado,
está apenas não-wired em end-to-end local.

---

## 5. Recomendação

| Pergunta | Resposta |
|---|---|
| Prompt 03 (D.4 Critic integration) é necessário? | **Sim** — F7 PARCIAL, Critic não wired no loop autônomo |
| Prompt 04 (F9 voyager) é necessário? | **Sim** — F9 TEÓRICA, SkillSynthesizer existe mas nunca rodou ciclo |
| Prompt 05 (F11 Web UI) é refazer ou ajustar? | **Ajustar** — webui/ e make_web_app() existem; falta wiring rotas + servir estáticos |
| Prompt 07 (F13 LoRA) precisa rodar ciclo novo? | **Sim** — finetune_runs=0, ciclo nunca executado |

**Ordem recomendada:** D.4 (Critic) → F9 (Voyager) → F11 (Web UI) → F13 (LoRA)
F12 (canais) pode ser feito em paralelo com F11 se houver recursos.
