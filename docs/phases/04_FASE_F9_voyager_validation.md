# FASE F9 — Validação Voyager Skills em Runtime Real

Projeto: **EVE_Autonomo** em `~/Desktop/agent`. Pré-requisito: `fase-d4-done`.

## Objetivo único

Provar que o gerador Voyager (já com código existente) realmente gera skills depois de 5+ ações similares, e que essas skills ficam disponíveis no próximo ciclo do agente. Se não estiver funcionando, conserta — esta fase pode escrever código.

## Regras duras

1. **NÃO pergunta.** Decide e executa.
2. **Skills geradas vão pra `skills/auto/` em formato Markdown** (não Python). Padrão herdado do EVE-Agent.
3. **Threshold: 5 ações similares em 30 dias.** Não muda esse valor.
4. **Skill auto-gerada tem que ter `auto_generated=true` na tabela `skills`.**
5. **Cada skill nova precisa de teste smoke** que prova que ela executa.

## Passos

### 1. Auditar o que existe

```bash
cd ~/Desktop/agent
find core/src -path '*voyager*' -o -name 'skill_generator*' | head
ls skills/ skills/auto/ 2>/dev/null
docker compose exec postgres psql -U agent -d agent -c \
  "SELECT count(*), count(*) FILTER (WHERE auto_generated=true) AS auto FROM skills;"
```

Salva achado em `F9_AUDITORIA.md`.

### 2. Decidir cenário

Se o gerador Voyager já existe e funciona → pula pro passo 5 e só roda smoke.
Se existe mas nunca rodou ciclo real → passo 3.
Se NÃO existe (foi marcado como "feito" sem implementar) → passo 4.

### 3. Disparar ciclo real (gerador existe)

Insere 6 invocações similares em `tool_executions` simulando histórico:

```bash
docker compose exec postgres psql -U agent -d agent -c "
INSERT INTO tool_executions (tool_name, args, result, success, created_at)
SELECT 'web_search',
       jsonb_build_object('query', 'preço dólar hoje ' || i),
       jsonb_build_object('top', 'R\$ 5,X' ),
       true,
       NOW() - (i || ' minutes')::interval
FROM generate_series(1,6) i;
"
```

Roda o consolidador:

```bash
PYTHONPATH=core/src ./.venv312/bin/python -c "
from agent.skills.voyager_generator import VoyagerSkillGenerator
import asyncio
async def main():
    gen = VoyagerSkillGenerator()
    new_skills = await gen.scan_and_generate()
    print('Geradas:', new_skills)
asyncio.run(main())
"
```

Esperado: pelo menos 1 skill nova em `skills/auto/*.md` E linha em `skills` com `auto_generated=true`.

### 4. Implementar do zero (se não existe)

Cria `core/src/agent/skills/voyager_generator.py`:

```python
"""Gera skills Markdown a partir de padrões em tool_executions."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import asyncpg

SKILLS_DIR = Path(__file__).parent.parent.parent.parent.parent / "skills" / "auto"
THRESHOLD = 5
WINDOW_DAYS = 30

class VoyagerSkillGenerator:
    def __init__(self, db_url: str | None = None, llm=None):
        self.db_url = db_url
        self.llm = llm  # ModelRouter; se None, usa default

    async def scan_and_generate(self) -> list[str]:
        """Procura padrões frequentes e gera skills novas. Retorna nomes geradas."""
        patterns = await self._find_frequent_patterns()
        generated = []
        for pattern in patterns:
            if await self._already_has_skill(pattern):
                continue
            skill_md = await self._synthesize_skill(pattern)
            name = self._save_skill(skill_md, pattern)
            await self._register_skill(name, pattern)
            generated.append(name)
        return generated

    async def _find_frequent_patterns(self) -> list[dict]:
        """Agrupa tool_executions por (tool_name, hash_args_template) e filtra count >= THRESHOLD."""
        # implementa query agrupando por tool_name + chaves dos args, ignorando valores
        ...

    async def _synthesize_skill(self, pattern: dict) -> str:
        """Pede ao LLM pra escrever a skill em Markdown."""
        prompt = f"""Você é um gerador de skills. Recebe um padrão de uso frequente e escreve um arquivo Markdown ...
Padrão: {json.dumps(pattern, indent=2)}
Formato de saída:
# skill_name
## Descrição
## Quando usar
## Parâmetros
## Implementação (pseudocódigo)
"""
        return await self.llm.complete(prompt)

    def _save_skill(self, skill_md: str, pattern: dict) -> str:
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha1(json.dumps(pattern, sort_keys=True).encode()).hexdigest()[:8]
        name = f"auto_{pattern['tool_name']}_{h}"
        (SKILLS_DIR / f"{name}.md").write_text(skill_md)
        return name

    async def _register_skill(self, name: str, pattern: dict):
        # INSERT em skills com auto_generated=true
        ...

    async def _already_has_skill(self, pattern: dict) -> bool:
        ...
```

Cria também `core/tests/unit/test_voyager_generator.py` cobrindo:
- Detecta padrão frequente (≥5 ocorrências, mesma tool, args estruturalmente similares)
- Ignora padrão raro (<5)
- Não duplica skill já existente
- Salva arquivo em `skills/auto/`
- Registra row com `auto_generated=true`

### 5. Smoke real com agente

Roda o agente em loop autônomo por 10 minutos com missão genérica:

```bash
PYTHONPATH=core/src ./.venv312/bin/python -m agent.cli mission create \
  --tier FAST \
  --goal "Pesquise o preço do dólar 6 vezes em horários diferentes simulados"
PYTHONPATH=core/src ./.venv312/bin/python -m agent.cli scheduler run --once
```

Depois roda o consolidador novamente. Verifica:

```bash
ls -la skills/auto/
docker compose exec postgres psql -U agent -d agent -c \
  "SELECT name, auto_generated, created_at FROM skills WHERE auto_generated=true ORDER BY created_at DESC LIMIT 5;"
```

### 6. Validar reuso

Roda missão similar de novo e checa que a skill auto-gerada foi usada:

```bash
PYTHONPATH=core/src ./.venv312/bin/python -m agent.cli mission create \
  --tier FAST \
  --goal "Pesquise o preço do dólar hoje"

docker compose exec postgres psql -U agent -d agent -c \
  "SELECT skill_name, count(*) FROM skill_invocations WHERE skill_name LIKE 'auto_%' GROUP BY skill_name;"
```

Esperado: pelo menos 1 invocação de skill `auto_*`.

### 7. Commit + tag + push

```bash
git add -A
git commit -m "feat(f9): valida e fecha Voyager skill generation em runtime real

- Gerador identifica padrões com threshold=5 em janela de 30 dias
- Skills salvas em skills/auto/*.md com auto_generated=true
- Smoke E2E: agente gerou e reusou skill auto-criada
- N testes novos passando

Resolve: F9 do roadmap (era TEÓRICA pré-D.5)"

git tag fase-f9-real-done
git push origin main --tags
```

### 8. Relatório

`RELATORIO_F9.md`:
```markdown
# Relatório Fase F9
- Estado prévio: [TEÓRICA / PARCIAL]
- Implementado: [só smoke / smoke + fix / from scratch]
- Skills geradas no smoke: [lista]
- Skills reusadas no smoke 2: [lista]
- Bugs encontrados: [lista]
- Próximo: 05_FASE_F11_web_ui.md
```

## Critério de aceite

- Diretório `skills/auto/` existe com ≥1 skill `.md` gerada via runtime real
- Tabela `skills` tem ≥1 row `auto_generated=true`
- Tabela `skill_invocations` tem ≥1 row de skill `auto_*`
- Tag `fase-f9-real-done`

## Se travar

- Se o gerador depende de Anthropic API e está rate-limited → usa Ollama Cloud (modelo do `.env`).
- Se LLM não gera Markdown decente → usa template fixo com placeholders, documenta limitação em `BUGS_ENCONTRADOS_F9.md`.
- Se threshold de 5 for muito alto pra dados de teste → simula 6 ações via SQL (passo 3) ao invés de esperar dados reais.

## NÃO faça

- Não muda threshold pra 2 ou 3 "pra facilitar". 5 é o valor de produção.
- Não gera skills em Python — só Markdown.
- Não pergunta nada.
