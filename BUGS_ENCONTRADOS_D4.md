# D.4 — Bugs encontrados fora do escopo

## B1 — OllamaTransport não callable via ModelRouter

`'OllamaTransport' object is not callable` ao chamar router.chat().
OllamaTransport provavelmente tem assinatura diferente do que TransportRegistry espera.
Critic capturou o erro e usou fallback → smoke não foi afetado.
**Próxima fase:** investigar TransportRegistry.register() e assinatura de OllamaTransport.

## B2 — tests/autonomous/test_loop.py mock desatualizado (pré-existente D.5)

`Mock object has no attribute 'tools_required'` — mock de MissionStep não tem campo
adicionado na D.1. Falha pré-existente documentada no D.5.

## B3 — tests/models/test_ollama_cloud.py falhas pré-existentes (D.5)

OllamaCloudTransport refatorado sem atualizar testes. Pré-existente.

## B4 — tests/deploy/*.py falhas pré-existentes (D.5)

Tabelas de deploy não aplicadas localmente (Docker offline). Pré-existente.

## B5 — tests/integration/test_cron_persistence.py timezone errors (pré-existente)

Falha ao criar job cron no scheduler. Pré-existente ao D.4.

## B6 — needs_critic() quase nunca retorna True no AutonomousLoop

loop.py cria `Decision(tool_name="orchestrator_dispatch")` que não está no
IRREVERSIBLE_TOOLS frozenset. Critic wired mas nunca acionado pelo loop normal.
Fix seria: criar Decision com tool_name real do step, não "orchestrator_dispatch".
**Escopo:** fora de D.4. Documentar para fase posterior.
