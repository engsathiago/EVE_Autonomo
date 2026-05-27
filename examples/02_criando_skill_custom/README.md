# 02 — Criando uma Skill Custom

Skills são "receitas" que o agente pode invocar quando reconhecer o padrão. Cada skill é um arquivo Markdown.

## Anatomia de uma Skill

```markdown
---
name: backup-postgres
description: Faz backup do banco PostgreSQL para um diretório local
trigger: "fazer backup do postgres OU backup do banco OU dump do banco"
tools: [shell, filesystem]
requires_confirmation: true
irreversible: false
tags: [database, backup, ops]
---

1. Identifique o banco alvo (default: `agent`)
2. Crie o diretório `/backups/` se não existir
3. Execute `pg_dump -U agent -d {{ db_name }} -F c -f /backups/{{ db_name }}_{{ timestamp }}.dump`
4. Verifique que o arquivo foi criado e reporte o tamanho
5. Se o backup for maior que 100 MB, alerte o usuário
```

## Campos do frontmatter

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `name` | string | Identificador único (kebab-case) |
| `description` | string | Descrição curta do que faz |
| `trigger` | string | Padrões que ativam a skill (usado no match semântico) |
| `tools` | list | Tools que a skill pode usar |
| `requires_confirmation` | bool | Se requer aprovação humana antes de executar |
| `irreversible` | bool | Se a operação não pode ser desfeita |
| `tags` | list | Tags para organização |

## Passo a passo

### 1. Crie o arquivo

```bash
mkdir -p skills/_active/minha-skill
cat > skills/_active/minha-skill/skill.md <<'EOF'
---
name: contar-arquivos-py
description: Conta quantos arquivos Python existem em um diretório
trigger: "contar arquivos python OU quantos .py tem"
tools: [shell]
requires_confirmation: false
tags: [filesystem, count]
---

1. Execute `find {{ path | default('.') }} -name '*.py' -type f | wc -l`
2. Reporte o número total ao usuário
EOF
```

### 2. Recarregue as skills

```bash
agent skill list   # Sua skill deve aparecer aqui
```

### 3. Teste manualmente

```bash
agent skill run contar-arquivos-py
```

### 4. Teste via conversa

```bash
agent run "Quantos arquivos python tem no projeto?"
```

A EVE deve reconhecer o padrão e invocar sua skill automaticamente.

## Templating com Jinja2

Skills suportam variáveis Jinja2 no corpo:

```markdown
---
name: greet-user
trigger: "saudar OU dar olá"
---

Saúde {{ nome | default('amigo') }} com uma mensagem calorosa em {{ idioma | default('português') }}.
```

Invocação:

```bash
agent skill run greet-user --param nome=Thiago --param idioma=inglês
```

## Validação

Antes de subir a skill para produção:

```bash
agent skill validate contar-arquivos-py   # Verifica sintaxe e dependências
agent skill review contar-arquivos-py      # Pede review com LLM (sugestões)
```

## Skills auto-geradas

A EVE pode criar skills automaticamente observando sessões com 5+ tool calls bem-sucedidas:

```bash
# Após uma sessão produtiva:
agent skill create-from-session <conversation_id>

# Isso cria um draft em skills/_drafts/
# Você revisa, edita e move para skills/_active/
```

## Próximo passo

[03_configurando_telegram](../03_configurando_telegram/) — Conecte a EVE ao Telegram.
