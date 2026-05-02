# Adicionar uma Tool nova ao agente

## Quando usar
Quando o usuário pedir "adicione uma tool de X" ou "crie uma ferramenta Y".

## Passos
1. Crie `core/src/agent/tools/builtin/{nome}.py`
2. Herde de `BaseTool` (em `tools/base.py`)
3. Defina `name`, `description`, `input_schema` (JSON Schema), `async execute()`
4. Registre em `core/src/agent/tools/registry.py` no `register_builtin()`
5. Documente em `config/TOOLS.md`
6. Crie teste em `core/tests/tools/test_{nome}.py`
7. Rode `pytest core/tests/tools/test_{nome}.py` pra confirmar

## Padrão
Veja `tools/builtin/web_search.py` como referência canônica.
