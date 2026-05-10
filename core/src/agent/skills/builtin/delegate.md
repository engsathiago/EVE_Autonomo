---
name: delegate
version: 1
description: Delegar uma sub-tarefa a um subagente isolado. Útil para escopo restrito ou execução paralela. O subagente não vê o histórico desta conversa.
arguments:
  - name: task
    type: string
    required: true
    description: Descrição precisa da sub-tarefa a executar.
  - name: tools
    type: string
    required: false
    description: "Tools que o subagente pode usar, separadas por vírgula (ex: web_search,calculator)."
  - name: timeout
    type: integer
    required: false
    description: Timeout em segundos (default 120).
  - name: return_format
    type: string
    required: false
    description: Formato da resposta (text, json, json_list).
  - name: extra_context
    type: string
    required: false
    description: Contexto adicional opcional para o subagente.
---

Delegue a sub-tarefa `{{ task }}` para um subagente isolado.
Tools autorizadas: {{ tools | default([]) | join(', ') or 'nenhuma' }}.
Retorne o resultado no formato: {{ return_format | default('text') }}.
