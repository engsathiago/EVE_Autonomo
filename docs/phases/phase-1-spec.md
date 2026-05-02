# Fase 1 — Core Mínimo (Agente Funcional)

> **Como usar:** Salve em `docs/phases/phase-1-spec.md`. Abra uma sessão
> NOVA do Claude Code. Cole esse arquivo inteiro. Antes de codar, peça:
> "Antes de codar, me dê o plano detalhado da Fase 1 baseado em
> docs/phases/phase-1-spec.md. Não escreva código ainda."

## Objetivo

Transformar a fundação da Fase 0 em um agente que **realmente funciona**.
Ao final, você consegue rodar `agent run` no terminal, conversar com a Eve,
ela usa tools (filesystem, shell, web search), e completa tarefas
autônomas simples.

**Sem memória persistente ainda.** **Sem skills auto-criadas.** **Sem
canais externos.** Tudo isso vem nas próximas fases. Aqui é só: agente +
tools + CLI.

## Pré-requisitos

- Fase 0 concluída e commitada
- `docker compose up` sobe os 4 serviços sem erro
- `.env` configurado com `ANTHROPIC_API_KEY` válida
- Nenhum arquivo de Fase 0 será modificado, exceto `CLAUDE.md` (atualizar
  estado) e `config/TOOLS.md` (documentar tools criadas)

## Entregas (resumo)

1. **Transport Anthropic** funcional com tool use
2. **Tool Registry** com sistema plugável
3. **3 tools nativas**: filesystem, shell, web_search
4. **AIAgent** com loop ReAct e reflexão
5. **CLI interativa** (`agent run`) com streaming
6. **Endpoint HTTP** `/api/chat` no core (preparação pra Gateway)
7. **Logger estruturado** consistente em todo o core
8. **Testes** unitários e de integração
9. **Documentação** atualizada

## Detalhamento técnico

### 1. Logger estruturado (`core/src/agent/observability/logger.py`)

Use `structlog`. Configurar para output JSON em produção, console colorido
em dev. Toda chamada deve incluir contexto: `request_id`, `agent_id`,
`tool_name` quando aplicável.

```python
import structlog

log = structlog.get_logger(__name__)

# uso:
log.info("tool.executed", tool_name="filesystem", duration_ms=42)
```

Configuração centralizada em `observability/__init__.py` lida no startup
do `server.py` e `cli/main.py`.

### 2. Configuração (`core/src/agent/config.py`)

Pydantic Settings carregando `config/config.yaml` + env vars. Estrutura:

```python
class AgentSettings(BaseSettings):
    name: str = "Eve"
    default_model: str = "claude-haiku-4-5"
    reflector_model: str = "claude-sonnet-4-6"
    max_iterations: int = 15
    reflection_every: int = 3

class AnthropicSettings(BaseSettings):
    api_key: str  # de ANTHROPIC_API_KEY
    base_url: str = "https://api.anthropic.com"
    timeout: int = 120

class Settings(BaseSettings):
    agent: AgentSettings
    anthropic: AnthropicSettings
    log_level: str = "INFO"
    
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        yaml_file="config/config.yaml",
    )
```

Nunca acessar variáveis de ambiente diretamente em outros módulos. Sempre
via `get_settings()`.

### 3. Transport base (`core/src/agent/transports/base.py`)

ABC com interface única:

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class ChatChunk(BaseModel):
    """Pedaço de resposta em streaming."""
    type: Literal["text", "tool_call_start", "tool_call_delta", "tool_call_end", "done"]
    text: str | None = None
    tool_call: dict | None = None

class ChatResponse(BaseModel):
    text: str
    tool_calls: list[dict]
    raw: dict
    usage: dict  # input_tokens, output_tokens

class BaseTransport(ABC):
    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> ChatResponse: ...
    
    @abstractmethod
    async def stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[ChatChunk]: ...
```

### 4. Transport Anthropic (`core/src/agent/transports/anthropic.py`)

Implementação concreta usando `anthropic.AsyncAnthropic`. Suporte a:

- Tool use nativo (formato Anthropic já é o canônico do projeto)
- Streaming via `messages.stream()`
- Retry com backoff exponencial em erros 429/503 (3 tentativas)
- Captura de usage em todas as respostas

Logs estruturados em cada chamada:

```python
log.info("transport.anthropic.request",
         model=model, message_count=len(messages),
         tools_count=len(tools or []))
log.info("transport.anthropic.response",
         input_tokens=resp.usage.input_tokens,
         output_tokens=resp.usage.output_tokens,
         tool_calls=len(tool_calls))
```

### 5. Registry de Transports (`core/src/agent/transports/registry.py`)

```python
_TRANSPORTS = {}

def register(name: str, factory):
    _TRANSPORTS[name] = factory

def get(name: str) -> BaseTransport:
    return _TRANSPORTS[name]()

# Em transports/__init__.py:
from .anthropic import AnthropicTransport
register("anthropic", lambda: AnthropicTransport())
```

### 6. Tool base (`core/src/agent/tools/base.py`)

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class ToolResult(BaseModel):
    ok: bool
    output: Any = None
    error: str | None = None
    
class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict
    requires_confirmation: bool = False
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult: ...
    
    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
```

### 7. Tool Registry (`core/src/agent/tools/registry.py`)

```python
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool) -> None: ...
    def get(self, name: str) -> BaseTool | None: ...
    def all_schemas(self) -> list[dict]: ...
    async def execute(self, name: str, args: dict) -> ToolResult:
        """
        Encapsula erros para nunca quebrar o loop do agente.
        Loga sempre via observability.logger.
        """

# singleton
def register_builtin(registry: ToolRegistry) -> None:
    """Registra todas as tools de tools/builtin/"""
    from .builtin.filesystem import ReadFileTool, WriteFileTool, ListDirTool
    from .builtin.shell import ShellTool
    from .builtin.web_search import WebSearchTool
    
    for cls in [ReadFileTool, WriteFileTool, ListDirTool, ShellTool, WebSearchTool]:
        registry.register(cls())
```

### 8. Tool: Filesystem (`core/src/agent/tools/builtin/filesystem.py`)

Três tools separadas (mais limpo que uma só):

**ReadFileTool**
- input: `path` (string)
- limita leitura a 1MB
- retorna conteúdo como string
- erro se path fora de um workspace permitido (whitelist via config)

**WriteFileTool**
- input: `path`, `content`, `mode` ("write" | "append")
- `requires_confirmation=True`
- cria diretórios pais se necessário
- limita escrita a 5MB

**ListDirTool**
- input: `path`, `recursive` (bool, default False)
- retorna lista de paths com tipo (file/dir) e tamanho

Whitelist de workspace em `config.yaml`:

```yaml
agent:
  workspace_paths:
    - "/workspace"
    - "/tmp/agent"
```

### 9. Tool: Shell (`core/src/agent/tools/builtin/shell.py`)

- input: `command` (string), `timeout` (int, default 30, max 300)
- `requires_confirmation=True`
- executa via `asyncio.create_subprocess_shell` em sandbox local
- captura stdout/stderr (max 100KB cada, trunca depois)
- retorna `{stdout, stderr, returncode, duration_ms}`
- **importante**: blacklist de comandos perigosos (rm -rf /, dd, mkfs, etc.)
  via regex em `config.yaml`

```yaml
agent:
  shell_blacklist:
    - "rm\\s+-rf\\s+/"
    - "mkfs"
    - "dd\\s+if="
```

### 10. Tool: Web Search (`core/src/agent/tools/builtin/web_search.py`)

Use **Tavily** como provider default (tem free tier generoso, simples).
Suporte a fallback para Brave Search se Tavily falhar.

- input: `query`, `max_results` (default 5)
- retorna lista de `{title, url, snippet, published_at?}`

```python
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Pesquisa na web. Use para informações atuais ou que você não tem certeza."
    
    async def execute(self, query: str, max_results: int = 5) -> ToolResult:
        provider = settings.search.provider  # "tavily" ou "brave"
        ...
```

Configuração:

```yaml
search:
  provider: "tavily"
  tavily:
    api_key: ${TAVILY_API_KEY}
  brave:
    api_key: ${BRAVE_API_KEY}
```

Adicionar em `.env.example`:

```
TAVILY_API_KEY=
BRAVE_API_KEY=
```

### 11. AIAgent core (`core/src/agent/core.py`)

O coração. Loop ReAct com reflexão.

```python
class AIAgent:
    def __init__(
        self,
        transport: BaseTransport,
        reflector_transport: BaseTransport | None,
        tool_registry: ToolRegistry,
        settings: AgentSettings,
    ):
        ...
    
    async def run(
        self,
        goal: str,
        on_event: Callable[[AgentEvent], Awaitable[None]] | None = None,
    ) -> AgentResult:
        """
        Executa o loop até concluir, estagnar, ou atingir limite.
        
        Eventos publicados via on_event:
          - iteration_start
          - planner_text (chunk de texto streaming)
          - tool_call (quando vai executar tool)
          - tool_result
          - reflection
          - done
        """
```

Detalhes do loop:

1. **Iteração**: até `max_iterations` (default 15)
2. **Plan + Act**: chama transport com histórico atual + tools
3. **Sem tool calls** = agente terminou, retorna `final_text`
4. **Com tool calls**: executa em paralelo (asyncio.gather), respeitando
   `requires_confirmation` (por enquanto auto-aprova; será revisto fase 5)
5. **Reflection** a cada `reflection_every` iterações:
   - Chama reflector_transport (Sonnet) com prompt de avaliação
   - Espera JSON `{progresso, problema, ajuste_estrategia}`
   - Se "estagnado": injeta hint no histórico
   - Se "concluido": força saída
6. **Histórico crescendo**: gerencia tool_use blocks corretamente
7. **Tracking**: total de tokens usados, custo estimado, duração

Arquivo `core/src/agent/prompts/system.py` com os prompts em constantes:

```python
PLANNER_SYSTEM = """Você é a Eve, um agente autônomo..."""
REFLECTOR_SYSTEM = """Você avalia se o agente está progredindo..."""
```

### 12. Streaming via eventos (`core/src/agent/events.py`)

```python
class AgentEvent(BaseModel):
    type: Literal["iteration_start", "planner_text", "tool_call",
                  "tool_result", "reflection", "done", "error"]
    data: dict
    timestamp: float
```

O `on_event` callback permite que CLI, HTTP e Gateway consumam o stream
do mesmo jeito.

### 13. CLI interativa (`cli/src/cli/main.py` e `cli/src/cli/repl.py`)

Use `typer` ou `click`. Comandos:

- `agent --version`
- `agent setup` (stub interativo — só valida .env)
- `agent run` (entra em REPL)

**REPL** (`repl.py`):

- Prompt colorido com nome do agente
- Histórico de comandos via `prompt_toolkit` (setas pra cima/baixo)
- Streaming de resposta token por token
- Exibe tool calls em destaque (cor diferente, formato compacto)
- Comandos especiais:
  - `/clear` — nova conversa (limpa histórico)
  - `/exit` — sai
  - `/cost` — mostra tokens/custo da sessão
  - `/tools` — lista tools disponíveis

Layout exemplo da resposta no REPL:

```
você > liste os arquivos do workspace e me diga qual tem mais linhas

eve  > Vou listar e analisar.

       🔧 list_dir(path="/workspace") 
       ↳ 5 arquivos encontrados
       
       🔧 read_file(path="/workspace/main.py")
       ↳ 234 linhas
       
       🔧 read_file(path="/workspace/utils.py")
       ↳ 89 linhas
       
       O arquivo `main.py` tem mais linhas (234), seguido de utils.py (89).

       ─ 1.2k tokens · $0.003 · 8s ─
```

### 14. Endpoint HTTP (`core/src/agent/server.py` — atualização)

Adicionar:

- `POST /api/chat` — body: `{message, conversation_id?}` — retorna resposta completa
- `POST /api/chat/stream` — body igual — retorna SSE com eventos
- `GET /api/tools` — lista tools disponíveis
- `GET /api/health` — já existe, mantém

Não precisa de auth ainda (vem na Fase 5).

### 15. Testes (`core/tests/`)

Estrutura espelhando `src/agent/`:

```
core/tests/
├── conftest.py                 # fixtures: mock_transport, registry, settings
├── test_config.py
├── transports/
│   └── test_anthropic.py       # com VCR ou mock
├── tools/
│   ├── test_filesystem.py
│   ├── test_shell.py
│   └── test_web_search.py      # mock HTTP
├── test_registry.py
├── test_core.py                # testa loop ReAct com mock_transport
└── integration/
    └── test_agent_run.py       # roda agent end-to-end com mock
```

**Cobertura mínima**: 70%. Cada arquivo de produção tem teste.

Use `respx` pra mockar HTTPX, `pytest-asyncio` pra async, fixtures
reutilizáveis.

### 16. Atualização de `config/TOOLS.md`

Documentar as 3 tools criadas com formato:

```markdown
## filesystem.read_file

Lê conteúdo de um arquivo dentro do workspace permitido.

**Inputs:**
- `path` (string, required): caminho absoluto

**Limites:**
- Máx 1MB por leitura
- Apenas paths em `agent.workspace_paths`

**Erros comuns:**
- `path_outside_workspace`: tentou acessar fora da whitelist
- `file_too_large`: arquivo > 1MB
```

### 17. Atualização de `CLAUDE.md`

Marcar `[x] Fase 1` no checklist.

## Critério de aceite

Após implementar tudo, rode na ordem:

```bash
# 1. Build e linting
cd core
uv pip install -e ".[dev]"
ruff check src/
mypy src/
pytest -v

# 2. Build Docker continua funcionando
cd ..
docker compose down
docker compose up --build -d
docker compose ps

# 3. Health check
curl http://localhost:8000/health
curl http://localhost:8000/api/tools | jq '.tools | length'
# deve retornar 5 (read_file, write_file, list_dir, shell, web_search)

# 4. Teste de chat HTTP
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Liste os arquivos em /tmp e me diga quantos são"}'

# 5. CLI funcional (fora do Docker)
cd core
python -m agent.cli.main run
# Conversar com a Eve interativamente
```

**Tudo deve passar**. Se falhar, debug antes de pedir Fase 2.

## Estimativa

- **Tempo do Claude Code**: 45-90 minutos
- **Tempo seu (acompanhar + debugar)**: 1-2 horas
- **Custo estimado**: $1-3 USD em tokens
- **Tamanho do diff**: ~3500 linhas adicionadas

## Dicas para essa fase específica

1. **Peça plano em duas partes** se ele tentar fazer tudo de uma vez:
   "Divida o plano em (a) infraestrutura — config, logger, transport, registry
   — e (b) lógica — agent core, CLI, tools. Implemente (a), valide, depois (b)."

2. **Use o subagente `core-builder`** que foi criado na Fase 0:
   ```
   @core-builder implemente os arquivos de config, logger e transport base.
   ```

3. **Se ficar muito grande**, peça `/compact` no meio.

4. **Validação parcial é ok**. Não precisa esperar tudo pronto pra testar
   peças isoladas.

## O que vem depois (preview)

**Fase 2 — Memória**: PostgreSQL + pgvector + curator + compressor.
A Eve vai começar a lembrar de você entre conversas.

**Fase 3 — Skills**: o agente cria skills sozinho após tarefas complexas.
