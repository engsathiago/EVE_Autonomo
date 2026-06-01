# Relatório Cleanup — Triagem de Bugs

## Fonte
Consolidado de BUGS_ENCONTRADOS_D1.md, BUGS_ENCONTRADOS_D4.md, BUGS_ENCONTRADOS_D5.md, BUGS_ENCONTRADOS_F9.md

---

## CRÍTICOS (consertados nesta fase)

### C1 — docker-compose.prod.yml ausente [D5-B7]
**Status:** RESOLVIDO — criado nesta fase.

---

## ALTOS (issues GitHub abertas)

### A1 — OllamaTransport não callable via ModelRouter [D4-B1, F9-B4]
Objeto `OllamaTransport` não é callable como transport no ModelRouter. Critic e Synthesizer
capturam o erro com fallback (template F9). Sistema funciona, mas modelos Ollama não são
usados quando configurados via ModelRouter.
**Issue:** #aberta

### A2 — needs_critic() nunca retorna True no AutonomousLoop [D4-B6]
`Decision(tool_name="orchestrator_dispatch")` não está no frozenset IRREVERSIBLE_TOOLS.
Critic está wired mas nunca acionado pelo loop normal. Somente quando o caller cria
Decision com tool_name real do step.
**Issue:** #aberta

---

## MÉDIOS (issues GitHub abertas)

### M1 — Gateway webhook/telegram retorna 404 [D5-B2]
`POST localhost:3000/webhook/telegram` → 404. Rota só existe em modo long-polling ativo.
F5 parcial — gateway funcional para outros endpoints.
**Issue:** #aberta

### M2 — AGENT_NO_WEB=1 workaround Starlette [Infra]
add_middleware dentro de lifespan não suportado pelo Starlette. Workaround: AGENT_NO_WEB=1
no docker-compose. Web UI serve corretamente via scripts/run_webui.py.
**Issue:** #aberta

### M3 — SkillSynthesizer não persiste skill_candidates automaticamente [F9-B2]
write_candidate() escreve em disco mas não chama save_candidate() no SkillRegistry.
Falta orquestrador (skill_pipeline runner) conectando os dois.
**Issue:** #aberta

---

## BAIXOS / TECH-DEBT

### L1 — F3/F9 skill systems incompatíveis [F9-B3]
F3 loader espera prompt.md; F9 gera skill.py + manifest.yaml. SkillManager (F3) não
reutiliza skills F9 diretamente.
**Issue:** #aberta (tech-debt)

### L2 — sandbox_executions não persiste via exec_tool em prod [D5-B4]
SandboxExecutor != SubprocessSandbox. Sandbox executa mas não loga no DB quando chamado
via exec_tool em alguns caminhos. F8 parcial.
**Escopo:** validação de runtime completa em v1.1.

---

## RESOLVIDOS (fechados)

- D1-B1, D1-B2, D1-B3, D1-B4 — pré-existentes de F5, resolvidos em Infra
- D4-B2, D4-B3, D4-B4, D4-B5 — resolvidos em Infra
- D5-B1 (tool_executions→skill_executions) — corrigido em D.5
- D5-B5 (skills.auto_generated) — campo tools_required adicionado em D.1
- D5-B6 (model_invocations.model) — ajustado em D.5
- D5-B8 (agent.web não exporta app) — WebUI serve via make_web_app()
- D5-B9 (VoyagerSkillGenerator) — SkillSynthesizer é o módulo correto
- F9-B1 (timed_out tipo errado) — corrigido em F9
