"""Testa MissionReflector — parse estrito e escrita em memória reflexiva."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.missions.reflector import MissionReflector, ReflectionParseError


_VALID_REFLECTION = """\
ENTREGUE:
- Publicados 8 cortes de saúde mental no Instagram
- Atingido média de 320 visualizações por corte

QUALIDADE:
Meta de 500 visualizações não atingida. Conteúdo bem recebido mas distribuição fraca.

PRÓXIMO:
Investir em tráfego pago nos 2 cortes com melhor engajamento orgânico.

APRENDIDO:
Cortes sobre ansiedade performam 2x mais que cortes sobre depressão neste público."""

_FREE_FORM_RESPONSE = """\
A missão foi concluída com sucesso! O agente publicou cortes e as métricas foram boas.
Ficou muito bom, parabéns ao time!"""


def _make_reflector() -> tuple[MissionReflector, MagicMock, MagicMock]:
    router = MagicMock()
    mission_store = MagicMock()
    reflexive_memory = MagicMock()

    # Setup padrão
    mission = MagicMock()
    mission.title = "Canal de cortes"
    mission.objective = "Lançar canal de saúde mental"
    mission.success_criteria = [{"criterion": "10 cortes", "verifiable_via": "manual"}]
    mission.status = "done"

    mission_store.get = AsyncMock(return_value=mission)
    mission_store.get_all_steps = AsyncMock(return_value=[])
    mission_store.get_critic_history = AsyncMock(return_value=[])
    mission_store.add_reflection = AsyncMock()

    reflexive_memory.add = AsyncMock()

    return MissionReflector(router, mission_store, reflexive_memory), mission_store, reflexive_memory


@pytest.mark.asyncio
async def test_reflector_strict_parse_rejects_free_form() -> None:
    """Formato livre sem os 4 campos deve lançar ReflectionParseError."""
    reflector, _, _ = _make_reflector()

    resp = MagicMock()
    resp.text = _FREE_FORM_RESPONSE
    reflector._router.chat = AsyncMock(return_value=resp)

    with pytest.raises(ReflectionParseError):
        await reflector.reflect(uuid4())


@pytest.mark.asyncio
async def test_reflector_writes_to_reflexive_memory() -> None:
    """Reflexão válida deve escrever o insight APRENDIDO na memória reflexiva."""
    reflector, mission_store, reflexive_memory = _make_reflector()

    resp = MagicMock()
    resp.text = _VALID_REFLECTION
    reflector._router.chat = AsyncMock(return_value=resp)

    mission_id = uuid4()
    reflection = await reflector.reflect(mission_id)

    # Insight deve ter sido gravado na memória reflexiva
    reflexive_memory.add.assert_called_once()
    call_kwargs = reflexive_memory.add.call_args
    insight_text = call_kwargs[0][0]  # primeiro arg posicional
    assert "ansiedade" in insight_text or "cortes" in insight_text.lower()

    # Reflection deve ter sido persistida na mission_store
    mission_store.add_reflection.assert_called_once()

    # Campos obrigatórios
    assert reflection.delivered
    assert reflection.quality_assessment
    assert reflection.learned
    assert "ansiedade" in reflection.learned or "cortes" in reflection.learned.lower()
