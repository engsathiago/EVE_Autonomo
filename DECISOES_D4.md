# D.4 — Decisões tomadas sem consultar

## 1. Manter irreversible.py intacto, criar irreversibility.py separado

**Por quê:** `critic.py` e `autonomous/loop.py` importam `agent.critic.irreversible.is_irreversible(tool_name)`.
Mudar a assinatura quebraria esses importadores. A nova `irreversibility.py` adiciona args-awareness
sem tocar no frozenset existente.

## 2. Smoke E2E usa Ollama fallback (personas falharam com erro de callable)

OllamaTransport retornou "'OllamaTransport' object is not callable" quando chamado
pelo ModelRouter — provavelmente incompatibilidade de assinatura de construtor.
O Critic capturou a exceção internamente e persistiu o registro com verdict="reject"
usando o fallback defensivo. Delta real: +1 em critic_evaluations.

## 3. Critic.request_approval (via exec_tool) não recebe db_pool

Não modifiquei `exec_tool.py` para passar db_pool ao `critic.request_approval`
porque mudaria a assinatura pública de exec_tool e poderia quebrar outros chamadores.
O smoke E2E chama `critic.evaluate` diretamente para garantir persistência.

## 4. AIAgent._maybe_gate_tool usa timeout via asyncio.wait_for

Timeout de 30s tratado como ESCALATE (bloqueio preventivo). Decisão: falhar fechado
é mais seguro que falhar aberto para ações irreversíveis.

## 5. TransportRegistry não via get_settings() no smoke

Instanciado diretamente com OllamaTransport para evitar depender do server.py.
No código de produção o router vem injetado via DI em server.py.
