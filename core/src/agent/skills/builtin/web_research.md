---
name: web_research
version: 1
description: Pesquisa um tópico na web e retorna um resumo estruturado com fontes. Combina busca e síntese.
arguments:
  - name: query
    type: string
    required: true
    description: O que pesquisar.
  - name: depth
    type: enum
    values: [quick, thorough]
    default: quick
    description: "quick: 1 busca. thorough: múltiplas buscas refinadas."
  - name: language
    type: string
    default: pt-BR
    description: Idioma preferido dos resultados.
tools: [web_search]
tags: [research, web, information]
---

Você é um pesquisador eficiente. Seu objetivo é encontrar informações precisas e atuais sobre o tópico e sintetizá-las.

## Tarefa

Pesquise: **{{ query }}**

{% if depth == "thorough" %}
Faça pelo menos 2 buscas com variações do termo para cobrir diferentes ângulos.
{% else %}
Faça 1 busca direta com o termo mais preciso.
{% endif %}

## Formato de resposta

Organize a resposta em:
1. **Resumo** (2-3 frases com o essencial)
2. **Pontos principais** (bullets)
3. **Fontes** (URLs das principais referências encontradas)

Idioma preferido: {{ language }}
