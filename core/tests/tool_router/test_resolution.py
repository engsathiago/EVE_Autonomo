"""
Testes unitários para tool_router.resolve_tools_for_step.

Cobertura: C2 (declared), C3 (keyword), C4 (llm cached), C5 (fallback),
           C6 (missing_tool), validate_declared_tools, MissingRequiredTool.

Todos os testes são unitários: LLM mockado, sem I/O, sem banco.
Cache do módulo é limpo em cada teste via fixture clear_llm_cache.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import agent.orchestrator.tool_router as _tr
from agent.orchestrator.tool_router import (
    ALWAYS_TOOLS,
    KNOWN_BUILTIN_TOOLS,
    StepSpec,
    resolve_tools_for_step,
    validate_declared_tools,
)
from agent.orchestrator.tiers import ExecutionTier
from agent.subagents.pool import MissingRequiredTool


# ─── Fixture: limpa o cache de inferência LLM entre testes ──────────────────

@pytest.fixture(autouse=True)
def clear_llm_cache():
    """Garante que o cache module-level não vaze entre testes."""
    _tr._llm_cache.clear()
    yield
    _tr._llm_cache.clear()


# ─── Helper ──────────────────────────────────────────────────────────────────

def _make_model_router(json_response: str) -> MagicMock:
    """Cria mock de ModelRouter que retorna json_response como texto."""
    router = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = json_response
    router.chat = AsyncMock(return_value=mock_resp)
    return router


# ─── C2 — Declarado ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_declared_passa_direto():
    """C2: tools_required explícito → source=declared, tools corretas, LLM não chamado."""
    router = _make_model_router('["web_search"]')  # não deve ser chamado
    spec = StepSpec(description="qualquer coisa", tools_required=["write_file"])

    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=router)

    assert res.source == "declared"
    assert "write_file" in res.tools
    # ALWAYS_TOOLS sempre presentes
    for t in ALWAYS_TOOLS:
        assert t in res.tools, f"{t!r} deveria estar em ALWAYS_TOOLS do resultado"
    # LLM não foi chamado
    router.chat.assert_not_called()


@pytest.mark.asyncio
async def test_declared_sem_model_router():
    """C2: source=declared funciona mesmo sem model_router (sem I/O LLM)."""
    spec = StepSpec(description="escrever arquivo", tools_required=["write_file"])
    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    assert res.source == "declared"
    assert "write_file" in res.tools


@pytest.mark.asyncio
async def test_declared_multiplas_tools():
    """C2: múltiplas tools declaradas chegam todas no set final."""
    spec = StepSpec(
        description="buscar e salvar",
        tools_required=["web_search", "write_file"],
    )
    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    assert res.source == "declared"
    assert "web_search" in res.tools
    assert "write_file" in res.tools
    # audit deve bater
    assert "web_search" in res.audit["tools_declared"]
    assert "write_file" in res.audit["tools_declared"]


# ─── C3 — Keyword ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keyword_write_file():
    """C3: descrição com 'salvar em' + 'buscar' → web_search + write_file inferidos."""
    router = _make_model_router('["web_search"]')  # não deve ser chamado
    spec = StepSpec(
        description="Buscar X na web e salvar em /tmp/y.json",
        tools_required=[],
    )

    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=router)

    assert res.source == "inferred_keyword"
    assert "web_search" in res.tools
    assert "write_file" in res.tools
    # LLM não foi chamado porque keyword casou
    router.chat.assert_not_called()


@pytest.mark.asyncio
async def test_keyword_read_file():
    """C3: 'ler arquivo' → read_file inferido."""
    spec = StepSpec(description="ler arquivo de configuração em /etc/app.conf", tools_required=[])
    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    assert res.source == "inferred_keyword"
    assert "read_file" in res.tools


@pytest.mark.asyncio
async def test_keyword_metafora_executar_nao_aciona_shell_via_keyword():
    """
    Anti-padrão §5: "executar o plano" é metáfora — o inferidor de KEYWORD
    não deve adicionar 'shell' com base nessa palavra isolada.

    O resultado final PODE conter 'shell' se cair no fallback STRATEGIC
    (que dá acesso total intencionalmente — disciplina vem do prompt).
    O teste verifica apenas que tools_inferred (a etapa de keyword) não
    incluiu 'shell' por causa da palavra metafórica.
    """
    spec = StepSpec(
        description="vamos executar o plano de marketing trimestral",
        tools_required=[],
    )
    # Sem model_router → nunca chega na inferência LLM; cai em fallback ou keyword.
    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    # Se veio de keyword, shell não deve estar nos inferred (metáfora)
    assert "shell" not in res.tools_inferred, (
        f"Keyword inferrer adicionou 'shell' por causa da metáfora 'executar' — "
        f"anti-padrão §5. tools_inferred={res.tools_inferred}, source={res.source!r}"
    )

    # Se veio de keyword (não fallback), shell também não deve estar no resultado final
    if res.source == "inferred_keyword":
        assert "shell" not in res.tools, (
            f"'shell' apareceu via inferred_keyword para descrição metafórica. "
            f"tools={res.tools}"
        )


# ─── C4 — LLM inferência ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_inferencia_strategic():
    """C4: descrição sem keyword + tier STRATEGIC → Haiku chamado, resultado cacheado."""
    router = _make_model_router('["read_file", "salvar_memoria"]')
    spec = StepSpec(description="analisar relatório financeiro de Q3", tools_required=[])

    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=router)

    assert res.source == "inferred_llm"
    assert "read_file" in res.tools
    # LLM chamado exatamente uma vez
    assert router.chat.call_count == 1


@pytest.mark.asyncio
async def test_llm_cache_hit_nao_chama_de_novo():
    """C4: segunda chamada com mesmo step → cache hit, LLM não chamado."""
    router = _make_model_router('["read_file", "salvar_memoria"]')
    spec = StepSpec(description="analisar relatório financeiro de Q3", tools_required=[])

    res1 = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=router)
    res2 = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=router)

    assert res1.source == "inferred_llm"
    assert res2.source == "inferred_llm"
    assert res1.tools == res2.tools
    # LLM chamado apenas na primeira vez
    assert router.chat.call_count == 1


@pytest.mark.asyncio
async def test_llm_inferencia_retorna_apenas_tools_conhecidas():
    """C4: LLM sugere tool inexistente → filtrada, não vaza para o resultado."""
    router = _make_model_router('["read_file", "tool_inventada_xyz"]')
    spec = StepSpec(description="tarefa técnica sem keyword clara", tools_required=[])

    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=router)

    # tool inexistente não deve aparecer
    assert "tool_inventada_xyz" not in res.tools
    # tool conhecida que o LLM sugeriu deve estar
    assert "read_file" in res.tools


# ─── C5 — Fallback ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_instant_nao_chama_llm():
    """C5: tier INSTANT com descrição ambígua → fallback sem chamar LLM."""
    router = _make_model_router('["web_search"]')
    spec = StepSpec(description="texto vago sem keyword nem sentido técnico claro", tools_required=[])

    res = await resolve_tools_for_step(spec, ExecutionTier.INSTANT, model_router=router)

    assert res.source == "fallback_default"
    # LLM não deve ter sido chamado para INSTANT
    router.chat.assert_not_called()
    # Set conservador esperado
    for t in ["web_search", "read_file", "salvar_memoria", "ler_memoria"]:
        assert t in res.tools


@pytest.mark.asyncio
async def test_fallback_fast_nao_chama_llm():
    """C5: tier FAST também não chama LLM — custo não justifica."""
    router = _make_model_router('["web_search"]')
    spec = StepSpec(description="algo vago sem padrão definido", tools_required=[])

    res = await resolve_tools_for_step(spec, ExecutionTier.FAST, model_router=router)

    assert res.source == "fallback_default"
    router.chat.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_strategic_sem_router_recebe_todas_tools():
    """C5: STRATEGIC sem model_router → fallback com todas as tools builtin."""
    spec = StepSpec(description="tarefa muito vaga que não bate nenhuma keyword", tools_required=[])

    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    assert res.source == "fallback_default"
    # STRATEGIC fallback = tudo disponível
    for t in KNOWN_BUILTIN_TOOLS:
        assert t in res.tools


# ─── C6 — Validação de tools declaradas ──────────────────────────────────────

def test_validate_declared_tools_detecta_ausente():
    """C6: tool inexistente no registry → detectada por validate_declared_tools."""
    missing = validate_declared_tools(["write_file", "tool_inexistente_xyz"])
    assert missing == ["tool_inexistente_xyz"]


def test_validate_declared_tools_tudo_existe():
    """C6: todas as tools existem → retorna lista vazia."""
    missing = validate_declared_tools(["write_file", "web_search"])
    assert missing == []


def test_validate_declared_tools_vazia():
    """C6: lista vazia → sem validação, retorna vazia."""
    assert validate_declared_tools([]) == []


def test_missing_required_tool_exception_campos():
    """C6: MissingRequiredTool contém missing e step_id acessíveis."""
    exc = MissingRequiredTool(missing=["xyz_tool"], step_id="step-abc-123")
    assert exc.missing == ["xyz_tool"]
    assert exc.step_id == "step-abc-123"
    assert "xyz_tool" in str(exc)
    assert "step-abc-123" in str(exc)


def test_missing_required_tool_sem_step_id():
    """C6: MissingRequiredTool sem step_id (chamada fora de missão) não explode."""
    exc = MissingRequiredTool(missing=["tool_a", "tool_b"])
    assert exc.step_id is None
    assert "tool_a" in str(exc)


# ─── ALWAYS_TOOLS ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_always_tools_sempre_presentes_em_declared():
    """ALWAYS_TOOLS aparecem mesmo quando declared não os listou."""
    spec = StepSpec(description="escrever resultado", tools_required=["write_file"])
    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    for t in ALWAYS_TOOLS:
        assert t in res.tools, f"ALWAYS_TOOL {t!r} ausente no resultado declared"


@pytest.mark.asyncio
async def test_sem_duplicatas_no_resultado():
    """Resultado não deve ter duplicatas mesmo quando ALWAYS_TOOLS coincidem com declaradas."""
    spec = StepSpec(
        description="salvar memória",
        tools_required=["salvar_memoria", "ler_memoria"],
    )
    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    assert len(res.tools) == len(set(res.tools)), "Resultado contém duplicatas"


# ─── Audit dict ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_declared_tem_campos_corretos():
    """Audit de declaração tem tools_declared correto para step_tool_routing."""
    spec = StepSpec(description="...", tools_required=["web_search"])
    res = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    assert res.audit["inference_source"] == "declared"
    assert "web_search" in res.audit["tools_declared"]
    assert res.audit["tools_inferred"] == []


@pytest.mark.asyncio
async def test_audit_fallback_tem_campos_corretos():
    """Audit de fallback tem inference_source=fallback_default."""
    spec = StepSpec(description="nada que case keywords", tools_required=[])
    res = await resolve_tools_for_step(spec, ExecutionTier.INSTANT, model_router=None)

    assert res.audit["inference_source"] == "fallback_default"
    assert res.audit["tools_declared"] == []
