---
name: mock_send_email
version: 1
description: Simula o envio de um email. Requer aprovação humana antes de executar.
requires_approval: true
approval_summary_template: |
  📧 Enviar email para **{{ to }}**
  Assunto: _{{ subject }}_

  {{ body[:200] }}{% if body|length > 200 %}...{% endif %}
arguments:
  - name: to
    type: string
    required: true
    description: Endereço de email do destinatário.
  - name: subject
    type: string
    required: true
    description: Assunto do email.
  - name: body
    type: string
    required: true
    description: Corpo do email.
tools: []
tags: [email, communication, demo]
model: anthropic:claude-haiku-4-5
---

Você é um assistente de escrita de emails.

Formate a seguinte mensagem como um email profissional e confirme que seria enviada:

**Para:** {{ to }}
**Assunto:** {{ subject }}
**Mensagem:**

{{ body }}

Responda confirmando que o email acima seria enviado. Não envie de verdade — este é um mock para demonstração do fluxo de aprovação.
