# Contribuindo com a EVE

Obrigado pelo interesse em contribuir com a EVE! Este guia vai te ajudar a começar.

## Antes de Começar

1. Leia o [README.md](README.md) para entender o projeto
2. Verifique as [issues abertas](https://github.com/seu-usuario/EVE_Autonomo/issues) para ver se alguém já está trabalhando no que você quer fazer
3. Para mudanças grandes, abra uma issue antes para discutir

## Preparando o Ambiente

### Pré-requisitos

- Python 3.11+
- Node.js 20+
- Docker e Docker Compose
- PostgreSQL 16 (ou use via Docker)
- Redis 7 (ou use via Docker)

### Setup Local

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/EVE_Autonomo.git
cd EVE_Autonomo

# Suba os serviços de infra (Postgres + Redis)
docker compose up postgres redis -d

# Configure o ambiente
cp .env.example .env
# Edite .env com suas credenciais

# Core Python
cd core
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Gateway Node
cd ../gateway
npm install
```

## Convenções de Código

### Python

- **async/await** em todo I/O
- **Type hints** sempre, validação com Pydantic v2
- **Imports absolutos:** `from agent.tools.registry import ...`
- **Logging estruturado** via `agent.observability.logger` (nunca `print()`)
- **Linting:** `ruff check .`
- **Formatação:** `ruff format .`

### TypeScript

- **Strict mode** no tsconfig
- **ESM** (`"type": "module"`)
- **Zod** para validação
- **Pino** para logs

### Geral

- Sem comentários óbvios — só explicar o "porquê", nunca o "o quê"
- Cada arquivo novo precisa de teste correspondente
- Não use `except: pass` (Python) nem `any` sem justificativa (TypeScript)
- Não hardcode credenciais — use variáveis de ambiente

## Commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: adicionar novo adaptador de canal WhatsApp
fix: corrigir timeout na conexão com Ollama
refactor: simplificar lógica do ContextCompressor
docs: documentar endpoint /v1/missions
test: adicionar testes para o CronParser
chore: atualizar dependências do gateway
```

## Processo de Contribuição

### 1. Fork e Branch

```bash
# Fork o repositório no GitHub, depois:
git clone https://github.com/seu-fork/EVE_Autonomo.git
cd EVE_Autonomo
git checkout -b feat/minha-feature
```

### 2. Implemente

- Siga as convenções de código
- Adicione testes para código novo
- Mantenha o agente funcional (não quebre o build)

### 3. Teste

```bash
# Python
cd core
pytest
ruff check .
ruff format --check .

# TypeScript
cd gateway
npm test
npm run build
```

### 4. Pull Request

- Título claro seguindo conventional commits
- Descrição explicando o que e por quê
- Referencie issues relacionadas
- Certifique-se de que todos os testes passam

## Estrutura do Projeto

Entender onde cada coisa fica é essencial:

| Diretório | Linguagem | Propósito |
|-----------|-----------|-----------|
| `core/src/agent/` | Python | Cérebro do agente (lógica, memória, skills, tools) |
| `core/tests/` | Python | Testes unitários e de integração |
| `core/migrations/` | SQL | Migrações de banco de dados |
| `gateway/src/` | TypeScript | Gateway de canais (Telegram, etc.) |
| `gateway/tests/` | TypeScript | Testes do gateway |
| `cli/src/cli/` | Python | CLI do agente |
| `webui/public/` | HTML/JS | Dashboard web |
| `config/` | YAML/MD | Configuração editável sem redeployar |
| `docs/` | Markdown | Documentação |

## Adicionando uma Nova Tool

1. Crie o arquivo em `core/src/agent/tools/builtin/`
2. Implemente a interface `BaseTool` com `name`, `description`, `input_schema`, `execute()`
3. Registre no `ToolRegistry`
4. Documente em `config/TOOLS.md`
5. Adicione testes

## Adicionando um Novo Canal

### Via Core Python (adaptador direto)

1. Crie o adaptador em `core/src/agent/channels/`
2. Herde de `BaseChannelAdapter`
3. Implemente `start()`, `stop()`, `send()`
4. Adicione no router em `core/src/agent/channels/router.py`
5. Documente as variáveis de ambiente em `.env.example`

### Via Gateway Node (bot dedicado)

1. Crie o diretório em `gateway/src/channels/`
2. Implemente o bot com a biblioteca do canal
3. Registre no `gateway/src/index.ts`
4. Adicione testes

## Adicionando uma Skill

Skills são arquivos markdown com frontmatter:

```markdown
---
name: minha-skill
trigger: "descrição do que ativa essa skill"
tools: [shell, filesystem]
---

Instruções passo-a-passo para o agente executar.
```

Coloque em `skills/_active/` para que seja carregada automaticamente.

## Reportando Bugs

Abra uma [issue](https://github.com/seu-usuario/EVE_Autonomo/issues/new) com:

1. **Descrição** clara do problema
2. **Passos para reproduzir**
3. **Comportamento esperado** vs **comportamento real**
4. **Logs relevantes** (sanitize credenciais!)
5. **Ambiente** (OS, versão do Python/Node, Docker version)

## Perguntas?

Abra uma issue com a tag `question` ou inicie uma [Discussion](https://github.com/seu-usuario/EVE_Autonomo/discussions).

---

Obrigado por ajudar a tornar a EVE melhor!
