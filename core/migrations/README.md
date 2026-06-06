# Migrations

Este diretório contém as migrations SQL numeradas do agente.

## Sistema de rastreamento

O runner (`agent.db.migrate`) usa a tabela `schema_migrations` (criada automaticamente).  
Não há dependência de Alembic ou de qualquer ferramenta externa.

## Numeração: começa em 002

A numeração começa em `002_memory_schema.sql`. Não existe `001_initial.sql` — e isso é
intencional. O runner simplesmente aplica os arquivos em ordem lexicográfica; ele não
exige que nenhum número específico exista. A ausência de 001 **não é um gap**: as tabelas
`conversations` e `messages` (que seriam candidatas a uma migration 001 hipotética) estão
definidas dentro de `002_memory_schema.sql`, que é a migration de bootstrapping do banco.

Em um banco virgem, `agent db migrate` aplica todas as migrations a partir de 002 sem erro.

## Adicionar uma nova migration

1. Nomeie o arquivo com o próximo número: `NNN_descricao_breve.sql`
2. Use `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, etc.
3. Rode `agent db migrate --dry-run` para confirmar que o arquivo será detectado.
4. O checksum SHA-256 é calculado automaticamente; não modifique migrations já aplicadas.
