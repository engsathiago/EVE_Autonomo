# Fase 3 — Sistema de Skills

> **Pré-requisitos:** Fases 0, 1 e 2 concluídas. Agente conversa, persiste mensagens, usa memória semântica via pgvector, e tem 3 tools fixas (web_search, file_ops, python_exec).

---

## 1. Objetivo

Substituir o conjunto fixo de tools por um **sistema de skills carregáveis em runtime**. Cada skill é uma unidade autocontida de capacidade — instruções em linguagem natural + tools associadas + metadados. O agente descobre skills disponíveis, escolhe a relevante pra tarefa, e a executa.

Além disso, o agente passa a **criar skills sozinho**: quando completa uma tarefa nova com sucesso, um processo de extração transforma a sequência de ações bem-sucedidas em uma skill nova reutilizável.

Ao final da Fase 3:
- Agente lista, busca e invoca skills por nome ou semanticamente.
- Skills vivem em `core/skills/` como arquivos `.md` + `manifest.yaml`.
- Existe um SkillManager que carrega, valida e executa skills.
- Existe um SkillCreator que extrai skills de execuções bem-sucedidas.
- Skills são versionadas e auditáveis via git.
- A CLI tem comandos `skill list`, `skill show <nome>`, `skill run <nome>`, `skill create-from-session`.

---

## 2. Arquitetura

```
┌──────────────────────────────────────────────────────────────┐
│                         AIAgent                              │
│                                                              │
│  ┌────────────┐   ┌──────────────┐   ┌─────────────────┐     │
│  │  Memory    │   │ SkillManager │   │  SkillCreator   │     │
│  │  (Fase 2)  │   │              │   │  (extrator)     │     │
│  └────────────┘   └──────┬───────┘   └────────┬────────┘     │
│                          │                    │              │
│                          ▼                    ▼              │
│                  ┌───────────────┐    ┌──────────────┐       │
│                  │ SkillRegistry │    │  Session log │       │
│                  │  (in-memory)  │    │  → skill .md │       │
│                  └───────┬───────┘    └──────────────┘       │
│                          │                                   │
│                          ▼                                   │
│              ┌─────────────────────────┐                     │
│              │  core/skills/*.md       │                     │
│              │  core/skills/*/         │                     │
│              │  manifest.yaml          │                     │
│              │  tools.py (opcional)    │                     │
│              └─────────────────────────┘                     │
└──────────────────────────────────────────────────────────────┘
```

### Fluxo de uso (happy path)

1. Usuário manda mensagem: "Resume o último episódio do PrimoCast em 5 bullets."
2. AIAgent pega a mensagem, consulta a Memory (Fase 2) por contexto.
3. AIAgent passa a mensagem pro SkillManager via `manager.match(message)`.
4. SkillManager faz busca semântica nas descrições das skills (usa o mesmo embedding model da Fase 2) e retorna top-3 candidatas.
5. AIAgent envia pra LLM o prompt do sistema **incluindo** as descrições das 3 skills candidatas + as ferramentas (tools) declaradas por cada uma.
6. LLM decide: invoca skill `summarize_youtube` com argumento `url=...`.
7. SkillManager executa: lê o `.md` da skill como prompt do sistema, injeta os argumentos, chama as tools declaradas, e devolve o resultado.
8. Resposta volta pro AIAgent, que persiste tudo (mensagens + skill_invocations) na memória.

### Fluxo de criação automática

1. Sessão termina com `session.outcome = "success"` (sinalizado pelo usuário ou inferido por heurística).
2. SkillCreator é chamado em background (via job assíncrono).
3. Lê o log da sessão (lista de mensagens + tool calls + resultados).
4. Manda pra LLM com prompt: "Esta sessão completou X com sucesso. Extraia as etapas reutilizáveis em formato de skill."
5. LLM produz draft de skill em markdown.
6. SkillCreator salva em `core/skills/_drafts/<nome>.md` (NÃO em produção — requer aprovação humana).
7. CLI tem comando `skill review` que lista drafts pra você aprovar/editar/descartar.

---

## 3. Estrutura de uma skill

### Skill simples (arquivo único)

`core/skills/summarize_text.md`:

```markdown
---
name: summarize_text
version: 1
description: Resume um texto em N bullets ou parágrafos. Útil pra notícias, artigos, transcrições.
arguments:
  - name: text
    type: string
    required: true
  - name: format
    type: enum
    values: [bullets, paragraphs]
    default: bullets
  - name: count
    type: integer
    default: 5
tools: []
tags: [text, summary, productivity]
---

# Skill: Resumir texto

Você é um resumidor preciso. Receba um texto e produza um resumo claro.

## Regras

- Se `format=bullets`, produza exatamente {{count}} bullets.
- Se `format=paragraphs`, produza {{count}} parágrafos curtos (max 3 frases cada).
- Não invente informação. Se o texto não diz, não diga.
- Use português do Brasil.

## Texto a resumir

{{text}}
```

### Skill composta (pasta com tools próprias)

`core/skills/publish_instagram_reel/`:

```
manifest.yaml      # metadados (mesmo formato do frontmatter)
prompt.md          # instruções
tools.py           # tools específicas (subclasse de Tool)
README.md          # doc humana opcional
```

`manifest.yaml`:

```yaml
name: publish_instagram_reel
version: 2
description: Publica um Reel no Instagram a partir de um arquivo de vídeo local. Faz upload, define legenda, agenda ou publica imediato.
arguments:
  - {name: video_path, type: string, required: true}
  - {name: caption, type: string, required: true}
  - {name: schedule_at, type: datetime, required: false}
tools: [InstagramUploadTool, CaptionFormatterTool]
tags: [content, instagram, eve]
requires_approval: true
```

`tools.py`:

```python
from core.tools.base import Tool

class InstagramUploadTool(Tool):
    name = "instagram_upload"
    description = "Faz upload de um vídeo pro Instagram via Graph API."
    # ... schema de args, run(), etc.

class CaptionFormatterTool(Tool):
    name = "caption_formatter"
    # ...
```

---

## 4. Arquivos a criar/modificar

### Novos arquivos

| Arquivo | Responsabilidade |
|---|---|
| `core/skills/__init__.py` | Marker do módulo |
| `core/skills/manager.py` | SkillManager: load, validate, match, run |
| `core/skills/registry.py` | SkillRegistry in-memory (cache) |
| `core/skills/loader.py` | Lê arquivos `.md` e pastas, parseia frontmatter/manifest |
| `core/skills/schema.py` | Pydantic models: SkillManifest, SkillArgument, SkillInvocation |
| `core/skills/creator.py` | SkillCreator: extrai skill de session log |
| `core/skills/runner.py` | Executa skill (renderiza prompt, chama LLM, executa tools) |
| `core/skills/builtin/summarize_text.md` | Skill builtin de exemplo |
| `core/skills/builtin/web_research.md` | Skill builtin que combina web_search + summarize |
| `core/skills/builtin/file_inspect.md` | Skill builtin pra inspecionar arquivos locais |
| `core/skills/builtin/extract_skill.md` | Skill que o creator usa pra extrair outras skills (meta-skill) |
| `tests/skills/test_loader.py` | Testes do loader |
| `tests/skills/test_manager.py` | Testes do manager (match, run) |
| `tests/skills/test_creator.py` | Testes do creator |
| `tests/skills/fixtures/` | Skills de teste |

### Arquivos a modificar

| Arquivo | Mudança |
|---|---|
| `core/agent.py` | Integrar SkillManager. Substituir tools fixas por skill matching. |
| `core/cli.py` | Adicionar `skill list`, `skill show`, `skill run`, `skill review`, `skill create-from-session` |
| `core/config.py` | Adicionar `SKILLS_DIR`, `SKILLS_AUTO_CREATE`, `SKILLS_DRAFTS_DIR` |
| `core/memory/schema.py` | Nova tabela `skill_invocations` (skill_name, args, result, session_id, latency_ms, success) |
| `core/memory/migrations/003_skill_invocations.sql` | Migration |
| `pyproject.toml` | Adicionar `python-frontmatter`, `jinja2` (pra templates), `pyyaml` se ainda não tem |
| `CLAUDE.md` | Atualizar status: Fase 3 concluída, padrão de skill, comandos novos |
| `docs/architecture.md` | Adicionar seção "Sistema de Skills" |

---

## 5. Schema do banco

Migration `003_skill_invocations.sql`:

```sql
CREATE TABLE skill_invocations (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    skill_version INTEGER NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    latency_ms INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX idx_skill_invocations_skill ON skill_invocations(skill_name, started_at DESC);
CREATE INDEX idx_skill_invocations_session ON skill_invocations(session_id);
```

Isso vai te dar telemetria pra Fase 8 (cron + reflexão).

---

## 6. Interface pública

### SkillManager

```python
class SkillManager:
    def __init__(self, skills_dir: Path, embedder: Embedder, db: Database):
        ...

    def load_all(self) -> int:
        """Carrega todas as skills do disco. Retorna quantidade."""

    def reload(self, name: str | None = None) -> None:
        """Recarrega uma skill específica (ou todas se None)."""

    def list(self, tag: str | None = None) -> list[SkillManifest]:
        """Lista skills. Opcionalmente filtra por tag."""

    def get(self, name: str) -> SkillManifest:
        """Retorna manifest de uma skill ou levanta SkillNotFound."""

    def match(self, query: str, k: int = 3) -> list[SkillMatch]:
        """Busca semântica + match por nome. Retorna top-k com score."""

    async def run(self, name: str, arguments: dict, session_id: UUID) -> SkillResult:
        """Executa skill. Persiste invocation. Levanta SkillError em falha."""
```

### SkillCreator

```python
class SkillCreator:
    def __init__(self, manager: SkillManager, llm: LLMClient, drafts_dir: Path):
        ...

    async def extract_from_session(self, session_id: UUID) -> Path | None:
        """
        Lê histórico da sessão, manda pra LLM com a meta-skill extract_skill,
        salva draft em drafts_dir. Retorna path do draft ou None se sessão
        não tinha conteúdo extraível.
        """

    def list_drafts(self) -> list[Path]: ...

    def promote(self, draft_path: Path) -> Path:
        """Move draft de _drafts/ pra core/skills/. Valida antes."""
```

---

## 7. Comportamento do AIAgent (mudança central)

Antes (Fase 1):

```python
# Tools fixas no construtor
agent = AIAgent(tools=[WebSearch(), FileOps(), PythonExec()])
```

Depois (Fase 3):

```python
agent = AIAgent(skill_manager=skill_manager, memory=memory)

# Em cada turno:
async def step(self, user_message: str, session_id: UUID) -> str:
    context = await self.memory.recall(user_message, k=5)
    candidates = self.skill_manager.match(user_message, k=3)
    
    system_prompt = self._build_system_prompt(context, candidates)
    tools_for_llm = self._collect_tools(candidates)
    
    response = await self.llm.chat(
        system=system_prompt,
        messages=[...],
        tools=tools_for_llm,
    )
    
    if response.tool_calls:
        for call in response.tool_calls:
            if call.is_skill_invocation:
                result = await self.skill_manager.run(
                    name=call.skill_name,
                    arguments=call.arguments,
                    session_id=session_id,
                )
                # ...
    
    return response.text
```

A LLM recebe as 3 skills candidatas como "tools" no formato nativo da API Anthropic. Skill = tool especial cujo `input_schema` vem do `manifest.yaml`.

---

## 8. CLI nova

```bash
agent skill list                        # lista todas
agent skill list --tag content          # filtra
agent skill show summarize_text         # mostra manifest + prompt
agent skill run summarize_text \
    --arg text="..." --arg count=3      # executa standalone (debug)
agent skill review                      # lista drafts pra aprovar
agent skill review --promote NOME       # promove draft
agent skill review --discard NOME       # descarta
agent skill create-from-session SESSION_ID   # força extração
agent skill validate PATH               # valida sintaxe de uma skill
```

---

## 9. Configuração

`.env` novo:

```
SKILLS_DIR=core/skills
SKILLS_DRAFTS_DIR=core/skills/_drafts
SKILLS_AUTO_CREATE=true
SKILLS_AUTO_CREATE_THRESHOLD=3   # mínimo de mensagens na sessão pra extrair
SKILLS_EMBEDDING_CACHE_DIR=.cache/skill_embeddings
```

---

## 10. Testes obrigatórios

1. **Loader**: parseia frontmatter, manifest.yaml, falha em skill inválida.
2. **Manager.match**: retorna top-k semanticamente relevante. Skill com nome igual à query tem boost.
3. **Manager.run** (skill simples): renderiza prompt com argumentos, chama LLM mock, retorna resultado. Persiste invocation no banco com sucesso=true.
4. **Manager.run** (skill com tool): tool é chamada com args certos, retorno é injetado na resposta.
5. **Manager.run** (falha): erro de tool é capturado, invocation persiste com sucesso=false e mensagem de erro.
6. **Creator.extract_from_session**: dado um log de sessão fixture, gera draft válido em _drafts/.
7. **Creator.promote**: move draft, recarrega no manager.
8. **Skill com `requires_approval: true`**: NÃO executa direto. Levanta `SkillRequiresApproval`. (Aprovação real fica pra Fase 5+ via Telegram; nesta fase só sinaliza.)
9. **Integração**: agente recebe mensagem, escolhe skill, executa, persiste tudo. End-to-end com banco real (test container).
10. **Performance**: load de 50 skills + match em < 100ms (excluindo cold start de embedder).

---

## 11. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Skill auto-criada de baixa qualidade vai pra produção | Drafts ficam em `_drafts/`, exigem `skill review --promote` manual. Nunca promovem sozinhos nesta fase. |
| Skill com `tools.py` malicioso (se vier de fora) | Loader valida que `tools.py` só importa de `core.tools.base` e bibliotecas allowlisted. Falha senão. |
| Embedding de descrições fica desatualizado quando edita skill | `loader` recalcula hash do manifest; se mudou, reembedda. Cache em `.cache/skill_embeddings/`. |
| Skill com nome duplicado | Loader falha no startup. Não silencia. |
| Match semântico ruim em domínio específico | Tags são canal de override: `match(query, must_have_tag=...)`. Boost por nome exato. |
| Argumentos da LLM não batem com schema | Pydantic valida antes de executar. Erro vai pro LLM no próximo turno pra ela corrigir. |
| Skill builtin é editada por engano | Builtin ficam em `core/skills/builtin/` e são read-only no manager (`promote` não sobrescreve). |
| Custo da LLM por turno cresce com muitas skills | Match retorna só top-k. Default k=3. Configurável. |

---

## 12. Critérios de aceitação

- [ ] `agent skill list` mostra ≥4 builtins.
- [ ] `agent skill show summarize_text` imprime manifest + prompt.
- [ ] `agent skill run summarize_text --arg text="<texto longo>" --arg count=3` retorna 3 bullets.
- [ ] Conversa real: usuário pede resumo → agente escolhe skill `summarize_text` → resposta correta.
- [ ] Tabela `skill_invocations` tem registros após uso.
- [ ] Sessão completa marcada como sucesso → draft aparece em `_drafts/`.
- [ ] `agent skill review --promote NOME` move draft e fica disponível no `list`.
- [ ] Todos os testes do passo 10 passando.
- [ ] `docker compose up -d` continua subindo limpo.
- [ ] CLAUDE.md atualizado com status e exemplos.

---

## 13. O que NÃO é Fase 3 (deixa pra depois)

- ❌ Aprovação via Telegram (Fase 5).
- ❌ Skills que rodam em sandbox isolado (Fase 9).
- ❌ Marketplace/registry remoto de skills (Fase 10).
- ❌ Multi-modelo dentro da skill (Fase 4).
- ❌ Skill que dispara outra skill em cadeia automática (Fase 8 — subagentes).
- ❌ Auto-promote de drafts baseado em métrica (Fase 8 — reflexão).

Mantenha disciplina. Se o Claude Code propor mais que isso, recuse.

---

## 14. Estimativa

- Sessão Claude Code: ~2-3h de execução, ~$2-3 USD.
- Você revisando: ~1h.
- Total wall-clock: meio dia se nada quebrar.
