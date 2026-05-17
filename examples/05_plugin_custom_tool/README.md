# 05 — Plugin: Custom Tool

Tools são as "mãos" da EVE. Aqui você aprenderá a criar uma tool como plugin externo, sem modificar o core.

Veja também: [docs/PLUGINS.md](../../docs/PLUGINS.md) para a referência completa.

## Anatomia de uma Tool

```python
from agent.tools.base import BaseTool
from pydantic import BaseModel, Field


class WeatherInput(BaseModel):
    cidade: str = Field(..., description="Nome da cidade")
    unidade: str = Field("celsius", description="celsius ou fahrenheit")


class WeatherTool(BaseTool):
    name = "get_weather"
    description = "Busca o clima atual de uma cidade"
    input_schema = WeatherInput
    requires_confirmation = False

    async def execute(self, params: WeatherInput) -> dict:
        # Lógica da tool aqui
        import httpx

        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"https://wttr.in/{params.cidade}",
                params={"format": "j1"},
                timeout=10.0,
            )

        data = r.json()
        temp_c = data["current_condition"][0]["temp_C"]

        if params.unidade == "fahrenheit":
            temp = float(temp_c) * 9/5 + 32
            unit = "°F"
        else:
            temp = float(temp_c)
            unit = "°C"

        return {
            "cidade": params.cidade,
            "temperatura": f"{temp:.1f}{unit}",
            "descricao": data["current_condition"][0]["weatherDesc"][0]["value"],
        }
```

## Onde colocar

A EVE varre `~/.agent/plugins/*.py` automaticamente:

```bash
mkdir -p ~/.agent/plugins
cp weather_tool.py ~/.agent/plugins/
```

Ou para o container Docker:

```bash
docker compose exec core mkdir -p /app/plugins
docker cp weather_tool.py eve_core_1:/app/plugins/
docker compose restart core
```

## Registro automático

O plugin loader procura por classes que herdam de `BaseTool` e as registra automaticamente:

```python
# Adicione no final do seu arquivo:
from agent.plugins.api import register_tool

register_tool(WeatherTool())
```

## Teste

```bash
agent run "Qual o clima em São Paulo?"
```

A EVE deve invocar a `get_weather` automaticamente.

Ou teste direto:

```bash
curl -X POST http://localhost:8000/v1/tools/get_weather \
  -H "Content-Type: application/json" \
  -d '{"cidade": "Rio de Janeiro", "unidade": "celsius"}'
```

## Tools que requerem confirmação

Para operações destrutivas:

```python
class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Deleta um arquivo do workspace"
    input_schema = DeleteFileInput
    requires_confirmation = True   # ← Pede aprovação humana
    irreversible = True             # ← Marca como irreversível

    async def execute(self, params):
        # ...
```

Quando a EVE quiser usar essa tool, ela primeiro cria um `pending_approval` e aguarda você aprovar via Telegram/Web UI.

## Boas práticas

✅ **Faça:**
- Use `pydantic.BaseModel` para input/output (validação automática)
- Use `async/await` em I/O (a EVE roda em asyncio)
- Levante exceções claras (`ToolError(...)`)
- Documente parâmetros com `Field(..., description=...)`
- Trate timeouts explicitamente
- Logue via `agent.observability.logger`

❌ **Não faça:**
- Bloqueie a event loop com chamadas síncronas pesadas
- Use `print()` (use o logger)
- Hardcode credenciais (use env vars)
- Acesse o filesystem fora de `workspace_paths`
- Faça operações destrutivas sem `requires_confirmation=True`

## Tools com permissões granulares

```python
class S3UploadTool(BaseTool):
    name = "s3_upload"
    description = "Upload de arquivo para S3"
    input_schema = S3UploadInput
    requires_confirmation = True
    irreversible = False
    permissions = ["network:s3", "filesystem:read"]   # Documentado, ainda não enforced
```

## Próximo passo

[06_finetuning_workflow](../06_finetuning_workflow/) — Workflow completo de fine-tuning.
