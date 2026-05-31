# D.1 — Bugs encontrados fora do escopo

## 1. test_autonomous/test_loop.py — 2 falhas pré-existentes

`test_loop_does_not_call_llm_directly` e `test_loop_respects_max_steps_per_tick`
falham por mock desatualizado — `AutonomousLoop` recebeu novo parâmetro
`mission_executor` que os mocks não fornecem.

**Status:** pré-existente ao D.1, não introduzido aqui.

## 2. test_deploy/test_persistence.py — 4 falhas + 5 errors pré-existentes

Testes de schema de deploy falham porque migration ainda não foi aplicada
no ambiente local (Docker Postgres não rodando). Errors são de conexão recusada.

**Status:** pré-existente, Docker offline.

## 3. test_models/test_ollama_cloud.py — 6 falhas pré-existentes

`OllamaCloudTransport` foi refatorado e os testes existentes não foram atualizados.

**Status:** pré-existente ao D.1.

## 4. tests/agent/memory/test_store.py — error pré-existente

Requer PostgreSQL rodando localmente. Docker offline.

**Status:** pré-existente, documentado desde F5.
