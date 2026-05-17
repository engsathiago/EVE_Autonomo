# 01 — Primeira Conversa com a EVE

Este é o "hello world" da EVE. Vamos enviar uma mensagem e receber a resposta de 3 formas: CLI, API REST e Web UI.

## Pré-requisitos

EVE rodando localmente:

```bash
docker compose up -d
curl http://localhost:8000/health   # {"ok": true}
```

## 1. Via CLI

```bash
agent run "Quem é você?"
```

Saída esperada (formatada com Rich):

```
🤖 EVE
Olá! Sou a EVE, uma assistente autônoma de engenharia. Como posso ajudar?

📊 1 iteração • 850 tokens • $0.0008 • 1.2s
```

## 2. Via API REST

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Quem é você?",
    "model": "anthropic:claude-haiku-4-5"
  }' | jq
```

Resposta:

```json
{
  "response": "Olá! Sou a EVE...",
  "conversation_id": "abc-123-def",
  "iterations": 1,
  "total_input_tokens": 312,
  "total_output_tokens": 538,
  "estimated_cost_usd": 0.0008,
  "duration_s": 1.23
}
```

## 3. Continuando uma conversa

Use o `conversation_id` retornado para manter contexto:

```bash
agent run --conversation-id abc-123-def "Liste suas capacidades"
```

Ou via API:

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Liste suas capacidades",
    "conversation_id": "abc-123-def"
  }'
```

## 4. Via Web UI

Abra http://localhost:8000 no navegador. Use o painel **Chat** para conversar visualmente.

## O que aconteceu nos bastidores?

1. Sua mensagem entrou no `AIAgent` (loop ReAct)
2. O `Planner` (Claude Haiku) decidiu que não precisava de tools — só responder
3. A resposta foi persistida na tabela `messages`
4. O `Curator` (em background) decidiu se a conversa gera memória durável
5. Os custos foram registrados em `model_invocations`

## Próximo passo

Vá para [02_criando_skill_custom](../02_criando_skill_custom/) para aprender a criar suas próprias skills.
