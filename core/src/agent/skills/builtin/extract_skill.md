---
name: extract_skill
version: 1
description: Meta-skill interna. Analisa o log de uma sessão bem-sucedida e extrai as etapas reutilizáveis em formato de skill Markdown com frontmatter.
arguments:
  - name: session_log
    type: string
    required: true
    description: JSON com a lista de mensagens e tool_calls da sessão.
  - name: task_description
    type: string
    required: true
    description: Descrição do que a sessão completou com sucesso.
tools: []
tags: [meta, skill-creation, internal]
---

Você é um engenheiro de skills. Sua tarefa é analisar uma sessão de agente bem-sucedida e extrair um skill reutilizável.

## Log da sessão

```json
{{ session_log }}
```

## O que foi completado

{{ task_description }}

## Sua tarefa

Produza um arquivo Markdown de skill com frontmatter YAML válido. O arquivo deve:

1. Ter um `name` em snake_case descritivo (ex: `summarize_youtube_video`).
2. Ter uma `description` de 1-2 frases que explique QUANDO usar esta skill.
3. Listar os `arguments` com nome, tipo e se são obrigatórios.
4. Listar as `tools` que a skill precisa (apenas as que foram realmente usadas).
5. Ter `tags` relevantes (2-5).
6. Ter um `prompt` claro com instruções usando `{{ argument_name }}` para injetar argumentos.

## Formato de saída

Produza APENAS o conteúdo do arquivo .md, sem explicações adicionais. Comece com `---`.

## Restrições

- Não invente tools que não existam. Use apenas: `web_search`, `read_file`, `write_file`, `run_shell`.
- Se a sessão não tiver padrão reutilizável claro, produza APENAS a string `NO_SKILL` sem mais nada.
- O prompt deve ser genérico o suficiente para funcionar com outros inputs, não apenas os da sessão original.
