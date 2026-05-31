# D.4 — Mapeamento

## Caminho real do executor
- AIAgent._execute_tools: core/src/agent/core.py:331
- Tool execution: registry.execute(name, args) em core.py:386
- AIAgent não tem critic nem db_pool atualmente

## Critic
- Módulo: agent.critic.critic.Critic
- Irreversível (por nome): agent.critic.irreversible.is_irreversible(tool_name) → bool
- Critic.evaluate(decision, db_pool=pool) → persiste em critic_evaluations
- Critic.request_approval(cmd, policy_name) → bool (sem db_pool, não persiste)
- Critic já integrado em autonomous/loop.py:201 mas needs_critic() quase sempre False
  (decision.tool_name="orchestrator_dispatch" não está no frozenset)
- skills/promoter.py usa critic.evaluate sem db_pool (não persiste)

## Sandbox
- exec_tool.py já tem SandboxRegistry wired (sandbox_executions)
- POLICY_UNTRUSTED.require_critic_approval=True (já chama critic via exec_tool)
- critic.request_approval() NÃO passa db_pool → não persiste em critic_evaluations
- Chamada direta SubprocessSandbox.run() sem exec_tool → não registra em DB

## Por que sandbox_executions=0
Smoke D.5 chamou SubprocessSandbox.run() diretamente → bypass de exec_tool e registry

## Por que critic_evaluations=9 (pré-existentes, sem novos)
Loop usa needs_critic(Decision(tool_name="orchestrator_dispatch")) → sempre False
critic.request_approval (via exec_tool) não passa db_pool → não persiste

## Solução mínima para delta ≥1 em ambas as tabelas
1. Call critic.evaluate(Decision(affects_external_world=True), db_pool=pool) → persiste
2. Call exec_tool(cmd, registry=SandboxRegistry(db_pool=pool)) → persiste
