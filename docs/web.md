# Web UI — F11

Dashboard terminal-style com 8 painéis, WebSocket multiplexado e autenticação por token.

## Como rodar

O Web UI sobe automaticamente com o serviço principal da F10:

```bash
agent deploy start
```

Para verificar se está rodando:

```bash
agent web status
```

## Como acessar

```bash
agent web open
```

Isso gera a URL com token e abre no browser padrão. URL resultante:

```
http://127.0.0.1:8080/?token=<TOKEN>
```

## Configuração inicial do token

Se ainda não tiver token:

```bash
agent web token-rotate
```

O token é salvo em `~/.agent/web_token` (chmod 600).

## Como rotacionar o token

```bash
agent web token-rotate
```

Sessões com token antigo expiram em até 5 segundos (cache TTL).

## Como ver o token atual

```bash
agent web token-show
```

Só funciona em TTY interativo.

## Acesso via SSH tunnel (outra máquina)

O painel é loopback-only (`127.0.0.1`). Para acessar de outra máquina:

```bash
ssh -L 8080:127.0.0.1:8080 user@host-do-agente
```

Depois abra `http://127.0.0.1:8080` localmente.

## Painéis disponíveis

| Painel | Conteúdo |
|--------|----------|
| Chat | Conversa direta com o agente via WebSocket |
| Missões | Lista de missões ativas/pausadas/concluídas |
| Skills | Skills manuais + auto-geradas (F9) com score do Crítico |
| Memória | Busca semântica na memória vetorial (pgvector) |
| Traces | Tasks e subagentes com timeline expansível |
| Crítico | Fila de decisões + histórico dos 3 vereditos |
| Subagentes | Health dos workers e execuções recentes |
| Aprovações | Aprovações pendentes do Telegram com botão de ação |

## Troubleshooting

### Token inválido / tela de auth

1. Verifique se o serviço está rodando: `agent web status`
2. Rotacione o token: `agent web token-rotate`
3. Use `agent web open` para abrir com o token correto

### Porta 8080 ocupada

Verifique quem está usando:

```bash
lsof -i :8080
# ou
ss -tlnp | grep 8080
```

Se for o serviço principal, está tudo certo. Se for outro processo, pare-o ou mude `AGENT_WEB_PORT` no `.env`.

### CSP bloqueando no browser

O painel usa CSP rígido. Se estiver usando DevTools para injetar scripts, o bloqueio é esperado. O painel funciona normalmente sem intervenção.

### Painel mostra "Erro: ..."

Verifique os logs do serviço:

```bash
agent deploy logs
```

O painel usa fallback defensivo — um adapter com erro não derruba os outros.

### Modo offline

O painel funciona 100% offline desde que:
- O serviço Python esteja rodando localmente
- As fontes JetBrains Mono estejam em `webui/public/assets/fonts/`

Se as fontes não estiverem presentes, o browser usa a stack de fallback (`Fira Code`, `Courier New`).

## Notas de segurança

- O painel é loopback-only. Bind em `127.0.0.1`, nunca `0.0.0.0`.
- Token de 32 bytes base64url, comparado via `hmac.compare_digest`.
- Sem cookies — tudo em `X-Agent-Token`.
- CSP rígido: sem `unsafe-eval`, sem `unsafe-inline` em `script-src`.
- Zero `innerHTML` em conteúdo dinâmico — `textContent` e `createElement`.

## Arquitetura

```
Browser → HTTP/WS → agent/web/server.py (FastAPI, mesmo processo F10)
                    ├── routes/api.py    (REST /api/v1/*)
                    ├── routes/ws.py     (WS /api/v1/stream, multiplexado)
                    ├── routes/static.py (serve webui/public/)
                    ├── auth.py          (X-Agent-Token, hmac)
                    └── adapters/        (wrappers finos p/ F3–F9)
```

O Web UI **não** armazena conteúdo de chat. Cada sessão de browser é independente.
O chat do painel não é o mesmo histórico do Telegram.
