# TOOLS.md — Documentação das Tools

> Este arquivo é populado progressivamente a cada fase.
> Cada tool tem: nome, descrição, parâmetros, limites e se requer confirmação.

## Tools disponíveis (Fase 1)

---

### read_file

**Descrição:** Lê o conteúdo de um arquivo dentro do workspace permitido.

**Parâmetros:**
- `path` (string, obrigatório): caminho absoluto do arquivo

**Requer confirmação:** Não

**Limites:**
- Máx 1 MB por leitura
- Apenas paths dentro de `agent.workspace_paths` (config.yaml)

**Erros comuns:**
- `path_outside_workspace`: tentou acessar fora da whitelist
- `file_too_large`: arquivo > 1 MB
- Arquivo não encontrado

---

### write_file

**Descrição:** Escreve ou concatena conteúdo em um arquivo dentro do workspace.

**Parâmetros:**
- `path` (string, obrigatório): caminho absoluto do arquivo
- `content` (string, obrigatório): conteúdo a escrever
- `mode` (string, opcional, default="write"): `"write"` substitui, `"append"` concatena

**Requer confirmação:** **Sim**

**Limites:**
- Máx 5 MB por escrita
- Apenas paths dentro de `agent.workspace_paths`
- Cria diretórios pais automaticamente

---

### list_dir

**Descrição:** Lista arquivos e diretórios dentro do workspace.

**Parâmetros:**
- `path` (string, obrigatório): caminho absoluto do diretório
- `recursive` (boolean, opcional, default=false): lista recursivamente

**Requer confirmação:** Não

**Retorno:** lista de `{path, type ("file"|"dir"), size}`

---

### shell

**Descrição:** Executa um comando shell. Comandos destrutivos são bloqueados por blacklist.

**Parâmetros:**
- `command` (string, obrigatório): comando shell a executar
- `timeout` (integer, opcional, default=30): timeout em segundos (máx 300)

**Requer confirmação:** **Sim**

**Limites:**
- Stdout/stderr truncados em 100 KB cada
- Comandos na blacklist (`agent.shell_blacklist` em config.yaml) são bloqueados

**Retorno:** `{stdout, stderr, returncode, duration_ms}`

---

### web_search

**Descrição:** Pesquisa na web via Tavily (fallback: Brave). Use para informações atuais.

**Parâmetros:**
- `query` (string, obrigatório): termos de busca
- `max_results` (integer, opcional, default=5): número máximo de resultados

**Requer confirmação:** Não

**Retorno:** lista de `{title, url, snippet, published_at}`

**Configuração:** definir `TAVILY_API_KEY` ou `BRAVE_API_KEY` no `.env`

---

## Template de documentação (para fases futuras)

```
### nome_da_tool

**Descrição:** O que a tool faz.

**Parâmetros:**
- `param1` (string, obrigatório): descrição
- `param2` (int, opcional, default=10): descrição

**Requer confirmação:** Sim / Não

**Exemplo:**
\`\`\`json
{ "param1": "valor", "param2": 5 }
\`\`\`
```
