# D.5 — Bugs encontrados (sem correção nesta fase)

## B1 — tool_executions não existe (spec errada)
Tabela referenciada no spec `tool_executions` não existe. Nome correto: `skill_executions`.
**Impacto:** query de baseline ajustada. Não bloqueia diagnóstico.

## B2 — Gateway webhook/telegram retorna 404
`POST localhost:3000/webhook/telegram` → 404 Not Found.
Gateway está rodando (health: OK) mas rota `/webhook/telegram` não está registrada.
**Impacto:** F5 não produz evidência em `channel_messages`. F5 = PARCIAL.
**Causa provável:** rota só existe em modo long-polling ativo (telegram.start()), não como rota HTTP standalone.

## B3 — Gateway core unreachable (degraded health)
`GET localhost:3000/health` → `{"status":"degraded","core":"unreachable"}`.
Core Python não está rodando localmente durante o smoke test.
**Impacto:** qualquer integração gateway→core falha. Afeta F5, F6.

## B4 — SandboxExecutor não existe (API incompatível)
`agent.sandbox.executor.SandboxExecutor` → ImportError. Módulo real é `SubprocessSandbox`.
API da spec não bate com implementação. Exec_tool também ausente como módulo standalone.
**Impacto:** sandbox roda (exit_code=0) mas não loga em `sandbox_executions`.
F8 = PARCIAL (executa, não persiste em DB).

## B5 — skills.auto_generated coluna ausente
Coluna `auto_generated` não existe na tabela `skills`.
Schema da F9 diverge do esperado (não foi migrado ou coluna foi removida).
**Impacto:** F9 smoke test não pode verificar skills auto-geradas via DB.

## B6 — model_invocations.model_name não existe
Coluna é `model` não `model_name`. Spec D.5 usa nome errado.
**Impacto:** query F13 ajustada. 0 invocações LoRA confirmadas.

## B7 — docker-compose.prod.yml ausente
Arquivo não existe. Deploy usa apenas `docker-compose.yml` + `deploy/digitalocean/deploy.sh`.
**Impacto:** F10 não valida compose de produção separado.

## B8 — agent.web não exporta 'app' no __init__.py
`from agent.web import app` → ImportError. Entry point é `make_web_app()` em `server.py`.
**Impacto:** web module importa via server, não __init__. Detalhe de API.

## B9 — VoyagerSkillGenerator não existe
`agent.skills.voyager_generator.VoyagerSkillGenerator` → ImportError.
Módulo real: `agent.skills.synthesizer.SkillSynthesizer`.
**Impacto:** F9 smoke test com API errada. Synthesizer existe mas não foi acionado.
