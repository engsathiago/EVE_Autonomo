# Fase 8 — Sandboxes de Execução

**Status anterior:** F7 (Missões + Crítico) concluída.
**Objetivo F8:** Toda execução de código/comando arbitrário do agente roda em ambiente isolado, com limites de recurso, rede controlada e filesystem efêmero. Nada que o agente gere ou execute pode tocar o host sem passar pela sandbox.

---

## 1. Princípios

- **Isolamento por padrão.** Qualquer `exec`, `shell`, `python eval`, `node eval`, ou skill que rode código vai pra sandbox. Sem exceção silenciosa.
- **Limites duros.** CPU, memória, tempo de parede (wall time), tamanho de output, tamanho de filesystem, network egress.
- **Filesystem efêmero.** Cada execução começa com FS limpo (ou snapshot read-only do template) e é destruído no fim.
- **Allowlist de rede.** Sem internet aberta. Domínios permitidos por skill/missão.
- **Observabilidade.** Toda execução gera trace: comando, exit code, stdout/stderr truncados, recursos consumidos, duração.
- **Nada de mágica.** Sandbox é uma classe Python concreta com backend selecionável. Sem vocabulário pomposo.

---

## 2. Arquitetura

```
agent/
  sandbox/
    __init__.py
    base.py              # Sandbox (ABC), SandboxConfig, SandboxResult
    docker_backend.py    # DockerSandbox (default)
    subprocess_backend.py # SubprocessSandbox (fallback, sem Docker)
    policy.py            # SandboxPolicy: limites, allowlist de rede, env vars
    registry.py          # SandboxRegistry: rastreia execuções ativas
    exceptions.py        # SandboxTimeout, SandboxOOM, SandboxNetworkDenied, etc.
  tools/
    exec_tool.py         # ferramenta `exec` exposta ao agente — usa Sandbox por dentro
```

### 2.1 `Sandbox` (interface)

```python
class Sandbox(ABC):
    @abstractmethod
    async def run(
        self,
        command: list[str] | str,
        *,
        stdin: bytes | None = None,
        files: dict[str, bytes] | None = None,  # arquivos pra colocar no FS antes de rodar
        env: dict[str, str] | None = None,
    ) -> SandboxResult: ...

    @abstractmethod
    async def cleanup(self) -> None: ...
```

### 2.2 `SandboxConfig`

```python
@dataclass
class SandboxConfig:
    image: str = "python:3.12-slim"        # só usado pelo DockerSandbox
    cpu_limit: float = 1.0                 # cores
    memory_limit_mb: int = 512
    wall_time_seconds: int = 30
    max_output_bytes: int = 1_000_000      # 1MB de stdout+stderr
    fs_size_mb: int = 256
    network: NetworkPolicy = NetworkPolicy.DENY_ALL
    allowed_domains: list[str] = field(default_factory=list)
    workdir: str = "/work"
    read_only_root: bool = True
```

### 2.3 `SandboxResult`

```python
@dataclass
class SandboxResult:
    exit_code: int
    stdout: str           # já truncado em max_output_bytes/2
    stderr: str
    duration_ms: int
    cpu_seconds: float
    memory_peak_mb: float
    timed_out: bool
    oom_killed: bool
    network_denied_attempts: list[str]  # domínios bloqueados
    files_out: dict[str, bytes]         # arquivos do /work no fim (se solicitado)
```

### 2.4 `NetworkPolicy`

```python
class NetworkPolicy(Enum):
    DENY_ALL = "deny_all"
    ALLOWLIST = "allowlist"     # usa SandboxConfig.allowed_domains
    OPEN = "open"               # SÓ permitido com flag explícita em SandboxPolicy.allow_open_network=True
```

---

## 3. Backends

### 3.1 DockerSandbox (default)

- Usa `docker run` com:
  - `--rm` (auto-remove)
  - `--network none` por padrão; ou network customizada com iptables/dnsmasq pra allowlist
  - `--memory`, `--cpus`, `--pids-limit 256`
  - `--read-only` na raiz, com tmpfs em `/work` e `/tmp` com `size=<fs_size_mb>m`
  - `--user 65534:65534` (nobody)
  - `--cap-drop=ALL`
  - `--security-opt no-new-privileges`
  - Sem `--privileged`. Sem montagens do host.
- Stdin via pipe.
- Files de input: copia pro container via `docker cp` antes do start, ou monta tmpfs com arquivos.
- Timeout via `asyncio.wait_for` + `docker kill` no estouro.
- Métricas via `docker stats --no-stream` ou cgroup direto.

### 3.2 SubprocessSandbox (fallback)

Usado quando Docker não tá disponível (ex: ambiente de teste, CI sem DinD). É mais fraco mas suficiente pra dev local.

- `asyncio.create_subprocess_exec` com:
  - `cwd` apontando pra `tempfile.TemporaryDirectory()`
  - `preexec_fn` que aplica `resource.setrlimit` (RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_NPROC)
  - Env vars filtradas (whitelist mínima: PATH, LANG, HOME aponta pro tmpdir)
- Timeout via `asyncio.wait_for` + `process.kill()` + `process.wait()`.
- **Limitação documentada:** não isola rede. Se `network != DENY_ALL`, levanta `SandboxBackendUnsupported`. Para `DENY_ALL` no subprocess backend, define `http_proxy=http://127.0.0.1:1` no env (best-effort; não é segurança real).
- Marca claramente no log: `backend=subprocess insecure=true`.

### 3.3 Seleção de backend

```python
def get_default_backend() -> type[Sandbox]:
    if shutil.which("docker") and _docker_daemon_responsive():
        return DockerSandbox
    return SubprocessSandbox
```

Override via env var `AGENT_SANDBOX_BACKEND=docker|subprocess`.

---

## 4. `SandboxPolicy` (camada de política, separada da config técnica)

Política é o que decide *se* uma execução pode rodar e *com que perfil*. Config é *como* roda.

```python
@dataclass
class SandboxPolicy:
    name: str                          # ex: "default", "skill_dev", "untrusted"
    config: SandboxConfig
    allow_open_network: bool = False   # gate explícito pra NetworkPolicy.OPEN
    require_critic_approval: bool = False  # se True, execução só passa após aprovação do Crítico (F7)
```

Perfis pré-definidos (em `policy.py`):

- `POLICY_DEFAULT`: 30s, 512MB, 1 CPU, network DENY_ALL.
- `POLICY_SKILL_DEV`: 120s, 1GB, 2 CPU, network ALLOWLIST com domínios da skill.
- `POLICY_UNTRUSTED`: 10s, 256MB, 0.5 CPU, network DENY_ALL, `require_critic_approval=True`.

---

## 5. Integração com o resto do sistema

### 5.1 Tool `exec` (substitui qualquer `subprocess.run` direto no código do agente)

```python
# agent/tools/exec_tool.py
async def exec_tool(
    command: list[str] | str,
    *,
    policy_name: str = "default",
    files: dict[str, bytes] | None = None,
    stdin: bytes | None = None,
    env: dict[str, str] | None = None,
) -> SandboxResult:
    policy = get_policy(policy_name)
    if policy.require_critic_approval:
        await critic.request_approval(command=command, policy=policy.name)
    sandbox = make_sandbox(policy.config)
    try:
        return await sandbox.run(command, files=files, stdin=stdin, env=env)
    finally:
        await sandbox.cleanup()
```

### 5.2 Orchestrator (F6)

Os tiers continuam iguais (INSTANT/FAST/STRATEGIC/EPIC), mas qualquer step que invoque execução de código **deve** chamar `exec_tool`. Adicionar lint/check no Orchestrator que rejeita steps que usem `subprocess`, `os.system`, `eval`, `exec` builtin diretamente.

### 5.3 SubagentPool (F6)

Cada subagent recebe sua própria policy (default = `POLICY_DEFAULT`). Subagents marcados como "untrusted" (ex: skills auto-geradas que ainda não passaram por validação na F9) usam `POLICY_UNTRUSTED`.

### 5.4 Crítico (F7)

`require_critic_approval=True` enfileira a execução pro Conclave de 3 personas. Aprovação destrava; rejeição vira `SandboxResult` com `exit_code=-1` e `stderr="critic_rejected: <razão>"`.

### 5.5 Event registry (F6)

Eventos novos:
- `sandbox.execution.started` — `{policy, backend, command_hash, sandbox_id}`
- `sandbox.execution.finished` — `{sandbox_id, exit_code, duration_ms, memory_peak_mb, timed_out, oom_killed}`
- `sandbox.network.denied` — `{sandbox_id, domain}`
- `sandbox.limit.exceeded` — `{sandbox_id, limit_type, value}`

---

## 6. Persistência e observabilidade

Tabela `sandbox_executions` (SQLite, mesma DB da memória de F0–F6):

```sql
CREATE TABLE sandbox_executions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    policy_name TEXT NOT NULL,
    backend TEXT NOT NULL,
    command_hash TEXT NOT NULL,
    command_preview TEXT NOT NULL,   -- primeiros 200 chars
    exit_code INTEGER,
    duration_ms INTEGER,
    memory_peak_mb REAL,
    cpu_seconds REAL,
    timed_out INTEGER NOT NULL DEFAULT 0,
    oom_killed INTEGER NOT NULL DEFAULT 0,
    network_denied_count INTEGER NOT NULL DEFAULT 0,
    mission_id TEXT,                  -- FK lógica pra missions (F7)
    subagent_id TEXT,                 -- FK lógica pra subagent_pool (F6)
    stdout_preview TEXT,
    stderr_preview TEXT
);

CREATE INDEX idx_sandbox_exec_mission ON sandbox_executions(mission_id);
CREATE INDEX idx_sandbox_exec_created ON sandbox_executions(created_at);
```

Toda execução grava 1 linha. Stdout/stderr completos vão pra arquivos em `logs/sandbox/<id>.{out,err}` (rotacionados por dia, 7 dias de retenção).

---

## 7. Estrutura de arquivos a criar

```
agent/sandbox/__init__.py
agent/sandbox/base.py
agent/sandbox/docker_backend.py
agent/sandbox/subprocess_backend.py
agent/sandbox/policy.py
agent/sandbox/registry.py
agent/sandbox/exceptions.py
agent/tools/exec_tool.py
agent/db/migrations/008_sandbox_executions.sql
docs/phase_8_sandbox.md
```

---

## 8. Critérios de aceitação

1. ✅ Existe classe `Sandbox` abstrata com `DockerSandbox` e `SubprocessSandbox` implementadas.
2. ✅ `exec_tool` é o único ponto de execução de comandos arbitrários no agente. Grep no repo por `subprocess.run`, `os.system`, `subprocess.Popen` fora de `agent/sandbox/` retorna zero ocorrências em código de produção (testes podem ter exceções marcadas).
3. ✅ Limites são respeitados: timeout mata o processo, OOM é detectado, output > limite é truncado, rede negada é registrada.
4. ✅ Filesystem é efêmero: dois `exec_tool` consecutivos não compartilham arquivos.
5. ✅ Política `POLICY_UNTRUSTED` integra com Crítico (F7) — execução só roda após aprovação.
6. ✅ Migration `008_sandbox_executions.sql` aplica e linha é gravada por execução.
7. ✅ Eventos `sandbox.*` emitidos no event_registry.
8. ✅ `AGENT_SANDBOX_BACKEND` env var muda o backend.
9. ✅ Backend é selecionado automaticamente se Docker disponível.
10. ✅ Documentação em `docs/phase_8_sandbox.md` com exemplos de uso e tabela de políticas.

---

## 9. Fora de escopo (F8)

- gVisor, Firecracker, Kata — fica pra F8.5 se F8 mostrar limitação real.
- Sandboxes de GPU.
- Quotas persistentes por subagent (acumuladas ao longo do tempo) — F10/F11.
- UI pra visualizar execuções — F11 (Web UI).

---

## 10. Branch e commit

- Branch: `feature/phase-8-sandbox`
- Commits atômicos: 1) base + exceptions, 2) subprocess backend, 3) docker backend, 4) policy + registry, 5) exec_tool + migration, 6) integrações (Orchestrator/Subagent/Critico/eventos), 7) docs.
- Tag ao fim: `phase-8-done`.
