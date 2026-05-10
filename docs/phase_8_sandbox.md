# Fase 8 — Sandboxes de Execução

Toda execução de código ou comando arbitrário gerado pelo agente passa por uma sandbox com limites de recurso, filesystem efêmero e rede controlada. Nada que o agente produza pode tocar o host sem passar por aqui.

---

## Arquitetura

```
exec_tool(command, policy_name="default")
     │
     ▼
get_policy(policy_name)          ← sandbox/policy.py
     │
     ├─ require_critic_approval?  ← critic.request_approval(command, policy)
     │
     ▼
make_sandbox(policy.config)      ← docker_backend.py (padrão) | subprocess_backend.py (fallback)
     │
     ▼
sandbox.run(command, files, env) → SandboxResult
     │
     ▼
registry.record(...)             ← sandbox_executions (PostgreSQL) + logs/sandbox/<id>.{out,err}
```

---

## Tabela de Políticas

| Política | Wall Time | Memória | CPU | Rede | Crítico |
|---|---|---|---|---|---|
| `default` | 30s | 512 MB | 1 core | DENY_ALL | Não |
| `skill_dev` | 120s | 1 GB | 2 cores | ALLOWLIST | Não |
| `untrusted` | 10s | 256 MB | 0.5 core | DENY_ALL | **Sim** |

**`default`**: uso geral — scripts, transformações de dados, geração de código rápida.

**`skill_dev`**: desenvolvimento de skills — tempo extra para instalar dependências, rede para acessar registries (configure `allowed_domains` antes de usar).

**`untrusted`**: skills auto-geradas que ainda não passaram por validação (F9). Toda execução passa pelo Conclave do Crítico antes de rodar.

---

## Backends

### DockerSandbox (padrão)

Ativado automaticamente quando `docker` está disponível e o daemon responde.

Flags de segurança aplicadas em cada `docker run`:
- `--rm` — auto-remove
- `--network none` (DENY_ALL) — sem acesso de rede
- `--memory=<N>m --memory-swap=<N>m` — limite de RAM sem swap
- `--cpus=<N>` — limite de CPU
- `--pids-limit=256` — previne fork bombs
- `--read-only` — raiz read-only
- `--tmpfs=/work:rw,size=<N>m,uid=65534` — workdir efêmero
- `--tmpfs=/tmp:rw,size=64m,uid=65534`
- `--user=65534:65534` — roda como nobody
- `--cap-drop=ALL` — sem capabilities
- `--security-opt=no-new-privileges`

**OOM**: Docker mata o container com SIGKILL (exit 137) quando o limite de memória é excedido. `SandboxResult.oom_killed=True` quando `exit_code == 137`.

### SubprocessSandbox (fallback)

Usado quando Docker não está disponível (CI sem DinD, dev local sem Docker).

Aplica `resource.setrlimit` para RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_NPROC.

**Limitações importantes:**
- Isolamento de rede não é garantido — `http_proxy=http://127.0.0.1:1` é best-effort, não é controle de segurança.
- Isolamento de filesystem é parcial — o processo roda em tmpdir mas pode acessar o host.
- `RLIMIT_AS` não está disponível no macOS (silenciosamente ignorado).

Adequado para: testes, desenvolvimento local.  
**Não adequado para: execução de código não confiável em produção.**

---

## Seleção de Backend

```python
# Automática (padrão)
make_sandbox(config)  # detecta Docker → usa DockerSandbox; senão SubprocessSandbox

# Forçado via env var
AGENT_SANDBOX_BACKEND=docker     # sempre Docker (falha se não disponível)
AGENT_SANDBOX_BACKEND=subprocess # sempre Subprocess
```

---

## Exemplos de Uso

### Execução simples (política default)

```python
from agent.tools.exec_tool import exec_tool

result = await exec_tool("python -c 'print(1+1)'")
print(result.stdout)      # "2\n"
print(result.exit_code)   # 0
```

### Com arquivos de input/output

```python
result = await exec_tool(
    "python process.py",
    policy_name="default",
    files={"process.py": b"import json; print(json.dumps({'ok': True}))"},
)
print(result.stdout)     # {"ok": true}
print(result.files_out)  # arquivos criados no /work durante execução
```

### Skill de desenvolvimento (rede permitida)

```python
from agent.sandbox.policy import POLICY_SKILL_DEV, SandboxPolicy
from agent.sandbox.base import SandboxConfig, NetworkPolicy

# Personaliza domínios permitidos
policy = SandboxPolicy(
    name="skill_dev",
    config=SandboxConfig(
        cpu_limit=2.0,
        memory_limit_mb=1024,
        wall_time_seconds=120,
        network=NetworkPolicy.ALLOWLIST,
        allowed_domains=["pypi.org", "files.pythonhosted.org"],
    ),
)

result = await exec_tool("pip install requests", policy_name="skill_dev")
```

### Execução não confiável (Crítico obrigatório)

```python
# Política "untrusted" requer aprovação do Conclave do Crítico.
# Sem instância de critic, a execução é bloqueada por default.
result = await exec_tool(
    "python untrusted_generated.py",
    policy_name="untrusted",
    critic=critic_instance,
)

if result.exit_code == -1 and "critic_rejected" in result.stderr:
    print("Execução bloqueada pelo Crítico")
```

---

## Quando usar qual perfil

| Situação | Política |
|---|---|
| Script de transformação de dados confiável | `default` |
| Geração/execução de código de um step de missão | `default` |
| Desenvolvimento e teste de nova skill | `skill_dev` |
| Skill que precisa baixar dependências | `skill_dev` |
| Skill auto-gerada pelo agente (F9) ainda sem validação | `untrusted` |
| Código enviado por usuário externo | `untrusted` |

---

## Observabilidade

### Banco de dados

Tabela `sandbox_executions` — 1 linha por execução com:
- Política usada, backend, hash do comando, preview do comando
- Exit code, duração, memória, CPU, flags de timeout/OOM
- Contagem de tentativas de acesso de rede negadas
- FK lógicas para `missions` e `tasks`
- Preview de stdout/stderr (500 chars)

### Logs de output completo

`logs/sandbox/<YYYY-MM-DD>/<sandbox_id>.out` e `.err`  
Rotação automática: 7 dias de retenção.

### Eventos no AgentEvent

| Evento | Dados |
|---|---|
| `sandbox.execution.started` | `sandbox_id`, `policy`, `backend`, `command_hash` |
| `sandbox.execution.finished` | `sandbox_id`, `exit_code`, `duration_ms`, `memory_peak_mb`, `timed_out`, `oom_killed` |
| `sandbox.network.denied` | `sandbox_id`, `domain` |
| `sandbox.limit.exceeded` | `sandbox_id`, `limit_type` (wall_time\|memory), `value` |

---

## Lint de Steps

O Orchestrator expõe `check_step_safety(step_code)` que rejeita código com padrões proibidos:

```python
violations = orchestrator.check_step_safety("""
import subprocess
subprocess.run(["ls"])  # proibido — use exec_tool
""")
# violations: ["Padrão proibido 'subprocess.run' na posição ... — use exec_tool"]
```

Padrões bloqueados: `subprocess.run/Popen/call/check_output/check_call`, `os.system()`, `eval()`, `exec()`.

---

## Fora de escopo (F8)

- gVisor, Firecracker, Kata — F8.5 se limites reais forem identificados.
- Sandboxes de GPU.
- Quotas acumuladas por subagente ao longo do tempo — F10/F11.
- UI para visualizar execuções — F11 (Web UI).
