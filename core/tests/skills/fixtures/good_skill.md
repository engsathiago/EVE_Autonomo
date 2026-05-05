---
name: good_skill
version: 2
description: Uma skill de teste válida para usar nos testes do loader.
arguments:
  - name: input_text
    type: string
    required: true
  - name: mode
    type: enum
    values: [fast, slow]
    default: fast
tools: []
tags: [test, fixture]
---

Você é um agente de teste. Processe: {{ input_text }} no modo {{ mode }}.
