# AGENTS.md — Regras Operacionais

> Comportamento do agente durante execução. Editável sem redeployar.

## Confirmações obrigatórias

Solicitar confirmação do usuário antes de:
- Deletar arquivos ou diretórios.
- Fazer push para repositórios remotos.
- Enviar mensagens em canais externos (Telegram, Discord, etc.).
- Executar migrações de banco de dados.
- Reiniciar serviços em produção.

## Política de erros

- Em caso de erro de tool, tentar 1 vez com abordagem alternativa antes de reportar.
- Erros de autenticação (401/403): reportar imediatamente, não tentar novamente.
- Timeouts: reportar após 2 tentativas com backoff de 5s.

## Política de memória

- Persistir como memória durável: decisões arquiteturais, preferências do usuário,
  contexto de projetos ativos.
- NÃO persistir: resultados intermediários, saídas de shell temporárias,
  conteúdo de arquivos grandes.
- Compressão de contexto: ativada quando > 50% do limite da janela.

## Iterações máximas

- Loop ReAct: 15 iterações por goal (configurável em config.yaml).
- Reflexão: a cada 3 iterações.
- QA loop: máximo 5 ciclos antes de escalar ao usuário.

## Aprovações

Timeout de aprovação: 120 segundos (configurável via APPROVAL_TIMEOUT_SECONDS).
Se não respondido no prazo: abortar a operação e notificar.
