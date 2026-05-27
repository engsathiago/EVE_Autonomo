# Desenvolvendo Plugins para a EVE

A EVE foi projetada para ser extensível sem precisar modificar o core. Você pode adicionar:

- **Tools** — novas capacidades (ex: `s3_upload`, `slack_post`)
- **Skills** — receitas reutilizáveis (Markdown, não código)
- **Transports** — novos providers de LLM
- **Channels** — novos canais de mensagem
- **Sandboxes** — novos backends de execução

---

## Onde os plugins ficam

A EVE varre os seguintes diretórios na inicialização:

| Diretório | O que carrega |
|-----------|--------------|
| `~/.agent/plugins/*.py` | Tools, transports, sandboxes |
| `skills/_active/*/` | Skills ativas |
| `~/.agent/skills/*/` | Skills do usuário (sobrescreve builtin) |

Para containers Docker, monte um volume:

```yaml
# docker-compose.override.yml
services:
  core:
    volumes:
      - ./meus-plugins:/app/plugins
```

---

## 1. Tools

### Interface

```python
from agent.tools.base import BaseTool
from pydantic import BaseModel


class MyInput(BaseModel):
    param1: str
    param2: int = 10


class MyTool(BaseTool):
    name: str                          # ID único
    description: str                   # Para o LLM decidir quando usar
    input_schema: type[BaseModel]      # Validação pydantic
    requires_confirmation: bool = False  # Aprovação humana
    irreversible: bool = False          # Operação não reversível

    async def execute(self, params: BaseModel) -> dict:
        # Sua lógica aqui
        return {"result": "..."}
```

### Registro

```python
from agent.plugins.api import register_tool

register_tool(MyTool())
```

### Ciclo de vida

1. **Carga:** loader varre `~/.agent/plugins/`
2. **Validação:** schema é validado contra Pydantic
3. **Exposição:** tool aparece em `agent.tools.registry.ToolRegistry`
4. **Invocação:** quando o LLM gerar tool_call, o registry resolve e executa

### Tools async vs sync

Sempre `async`. Para chamadas síncronas pesadas, use:

```python
import asyncio

async def execute(self, params):
    # Para CPU-bound:
    result = await asyncio.to_thread(heavy_sync_fn, params.x)

    # Para subprocess:
    proc = await asyncio.create_subprocess_exec(...)
```

---

## 2. Skills

Skills NÃO são código Python — são arquivos Markdown com frontmatter.

```markdown
---
name: meu-skill
description: O que ele faz
trigger: "palavras que ativam essa skill"
tools: [shell, filesystem]
requires_confirmation: false
irreversible: false
tags: [categoria1, categoria2]
---

1. Passo um
2. Passo dois com {{ variavel }}
3. Passo três
```

Veja [examples/02_criando_skill_custom](../examples/02_criando_skill_custom/) para detalhes.

---

## 3. Transports (Provider de LLM)

Para adicionar um novo provider (ex: Mistral, Cohere):

```python
from agent.models.base import BaseTransport, ChatResponse


class MistralTransport(BaseTransport):
    provider = "mistral"

    def __init__(self, api_key: str, base_url: str = None):
        self.api_key = api_key
        # ...

    async def chat(
        self,
        system: str,
        messages: list,
        tools: list = None,
        model: str = None,
    ) -> ChatResponse:
        # Chamada à API do provider
        # Normaliza response para ChatResponse
        return ChatResponse(
            text="...",
            tool_calls=[...],
            input_tokens=123,
            output_tokens=456,
            raw=raw_response,
        )

    async def health_check(self) -> bool:
        # Retorna True se o provider está respondendo
        ...

    async def list_models(self) -> list[str]:
        # Lista modelos disponíveis
        ...
```

### Registro

```python
from agent.models.registry import register_transport

register_transport(MistralTransport(api_key=os.getenv("MISTRAL_API_KEY")))
```

Depois você pode usar:

```bash
agent run --model mistral:mistral-large-latest "..."
```

---

## 4. Channels

Para adicionar um canal (ex: WhatsApp, SMS):

```python
from agent.channels.base import BaseChannelAdapter


class WhatsAppAdapter(BaseChannelAdapter):
    channel_id = "whatsapp"

    async def start(self):
        # Conecta ao provider (ex: Twilio, Meta Business API)
        ...

    async def stop(self):
        # Desconecta limpa
        ...

    async def send(self, recipient: str, message: str) -> bool:
        # Envia mensagem para recipient
        ...

    async def on_message(self, callback):
        # Registra callback para mensagens recebidas
        ...
```

### Configuração

Adicione no `config/config.yaml`:

```yaml
channels:
  whatsapp:
    enabled: false
    api_key: ${WHATSAPP_API_KEY}
    allowlist: ${WHATSAPP_ALLOWLIST}   # CSV obrigatório
```

⚠️ **Allowlist obrigatória:** Sem ela, o adapter não sobe (decisão de segurança).

---

## 5. Sandboxes

Para adicionar um backend de execução (ex: Kubernetes, AWS Lambda):

```python
from agent.sandbox.base import BaseSandbox, SandboxResult


class K8sSandbox(BaseSandbox):
    backend = "kubernetes"

    async def execute(
        self,
        code: str,
        language: str,
        policy: SandboxPolicy,
        timeout: int = 30,
    ) -> SandboxResult:
        # Cria pod efêmero
        # Executa código
        # Captura stdout/stderr
        # Limpa pod
        ...
```

---

## Estrutura recomendada de um plugin

```
meu-plugin-eve/
├── pyproject.toml          # Para distribuir via pip
├── README.md
├── tests/
│   └── test_my_tool.py
└── src/
    └── meu_plugin/
        ├── __init__.py
        └── tool.py
```

Exemplo de `pyproject.toml`:

```toml
[project]
name = "eve-plugin-clima"
version = "0.1.0"
dependencies = [
    "agent-core>=0.13",
    "httpx>=0.28",
]

[project.entry-points."agent.plugins"]
weather = "meu_plugin:WeatherTool"
```

Com `entry_points`, plugins podem ser instalados via:

```bash
pip install eve-plugin-clima
# Sem precisar copiar arquivos para ~/.agent/plugins/
```

---

## Testando plugins

```python
# tests/test_my_tool.py
import pytest
from meu_plugin import WeatherTool


@pytest.mark.asyncio
async def test_weather_tool_returns_temperature():
    tool = WeatherTool()
    result = await tool.execute(WeatherInput(cidade="São Paulo"))

    assert "temperatura" in result
    assert "°C" in result["temperatura"]
```

---

## Boas práticas

### ✅ Faça

- **Versione semanticamente** seu plugin
- **Documente o threat model** se o plugin acessa rede/filesystem
- **Use `requires_confirmation=True`** para tools destrutivas
- **Trate timeouts e erros explicitamente** (não deixe estourar)
- **Adicione testes** (a EVE valida via importação)
- **Use type hints** em todos os métodos

### ❌ Não faça

- Modifique código do core diretamente (perde nas atualizações)
- Use `requests` (síncrono) — use `httpx` async
- Hardcode credenciais
- Faça `print()` — use `agent.observability.logger`
- Acesse `MemoryStore` diretamente (use as tools `salvar_memoria` / `ler_memoria`)

---

## Distribuindo seu plugin

1. Publique no PyPI: `pip install eve-plugin-meu`
2. Adicione ao [Awesome EVE](https://github.com/engsathiago/EVE_Autonomo/wiki/Awesome-EVE) (lista comunitária)
3. Abra uma PR para mencionarmos no README

---

## Quero contribuir um plugin oficial

Plugins oficiais (mantidos pelo time da EVE) ficam em `core/src/agent/plugins/builtin/`. Para contribuir:

1. Abra uma issue propondo o plugin
2. Discutimos o escopo e interface
3. Você abre um PR com implementação + testes + docs
4. Após review e merge, o plugin entra no próximo release

Veja [CONTRIBUTING.md](../CONTRIBUTING.md) para o processo geral.
