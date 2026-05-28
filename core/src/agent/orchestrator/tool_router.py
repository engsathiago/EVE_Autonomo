"""
Tool Router — D.1: Resolve o conjunto de tools para um step de missão.

O set de tools deixa de ser função do TIER (estático) e passa a ser função
do STEP (dinâmico). Quatro estratégias em ordem de prioridade:

  1. declared   — step declarou tools_required explicitamente
  2. keyword    — analisa description do step por keywords
  3. inferred_llm — Haiku decide (só STRATEGIC/EPIC, cacheado 7 dias)
  4. fallback   — default seguro por tier

ALWAYS_TOOLS são sempre adicionadas ao conjunto final (independente da fonte).

Auditoria: toda resolução deve ser gravada em step_tool_routing via
`log_routing_audit()`. O chamador (router.py) é responsável por isso.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from agent.observability.logger import get_logger
from agent.orchestrator.tiers import ExecutionTier

if TYPE_CHECKING:
    import asyncpg
    from agent.models.router import ModelRouter

log = get_logger(__name__)

# ─── Constantes públicas ────────────────────────────────────────────────────

# Tools que SEMPRE aparecem no set final (memória de curto prazo do subagente).
ALWAYS_TOOLS: list[str] = ["salvar_memoria", "ler_memoria"]

# Todos os nomes de tools presentes no ToolRegistry builtin.
# Usado para validar tools declaradas e para o fallback STRATEGIC/EPIC.
KNOWN_BUILTIN_TOOLS: frozenset[str] = frozenset(
    ["read_file", "write_file", "list_dir", "shell", "web_search",
     "salvar_memoria", "ler_memoria", "delegate"]
)

# Map de padrões regex → tools inferidas.
# A ordem importa: primeiro match que encontrar keywords ganha.
# Mantido como módulo-level dict para auditabilidade — nenhum outro módulo
# deve importar ou duplicar esta lógica (ver test_lint_d1.py).
KEYWORD_TOOL_MAP: dict[str, list[str]] = {
    # Escrita de arquivo
    r"\b(escrever|salvar arquivo|salvar em|write.?file|gravar|criar arquivo)\b": ["write_file"],
    # Leitura de arquivo
    r"\b(ler arquivo|abrir arquivo|read.?file|cat |conteúdo do arquivo|lê o arquivo)\b": ["read_file"],
    # Listagem de diretório
    r"\b(listar|ls |list.?dir|ls$|diretório|directory listing)\b": ["list_dir"],
    # Busca na web
    r"\b(buscar na web|pesquisar na web|search the web|web search|pesquisa online|procurar online)\b": ["web_search"],
    # Busca genérica (menor prioridade que web)
    r"\b(pesquisar|buscar|search|procurar)\b": ["web_search"],
    # Memória
    r"\b(memória|lembrar|lembra|histórico de memória|memory store)\b": ["salvar_memoria", "ler_memoria"],
    # Shell — keyword "executar" só matcheia se acompanhado de contexto técnico
    # Spec anti-pattern: "executar o plano" é metáfora, não precisa de shell.
    r"\b(rodar script|executar script|bash |sh |python .+\.py|shell command|run command|execute command)\b": ["shell"],
}


# ─── Tipos ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StepSpec:
    """Snapshot mínimo de um step — não importa MissionStep para evitar acoplamento."""

    description: str
    tools_required: list[str] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash((self.description, tuple(self.tools_required)))


@dataclass(frozen=True)
class ToolResolution:
    """Resultado da resolução de tools para um step."""

    tools: list[str]              # set final que o subagente receberá (inclui ALWAYS_TOOLS)
    source: str                   # declared | inferred_keyword | inferred_llm | fallback_default
    audit: dict                   # campos para gravar em step_tool_routing
    # Campos de rastreabilidade (espelham audit, para acesso direto nos testes)
    tools_declared: list[str] = field(default_factory=list)   # tools vindas de tools_required
    tools_inferred: list[str] = field(default_factory=list)   # tools vindas de keyword/LLM


# ─── Cache de inferência LLM ─────────────────────────────────────────────────

_LLM_CACHE_TTL_S: int = 7 * 24 * 3600   # 7 dias

@dataclass
class _CacheEntry:
    tools: list[str]
    created_at: float


_llm_cache: dict[str, _CacheEntry] = {}


def _cache_key(step_spec: StepSpec, tier: ExecutionTier) -> str:
    raw = json.dumps(
        {"desc": step_spec.description[:500], "req": sorted(step_spec.tools_required), "tier": tier.value},
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_get(key: str) -> list[str] | None:
    entry = _llm_cache.get(key)
    if entry and (time.monotonic() - entry.created_at) < _LLM_CACHE_TTL_S:
        return entry.tools
    return None


def _cache_set(key: str, tools: list[str]) -> None:
    _llm_cache[key] = _CacheEntry(tools=tools, created_at=time.monotonic())


# ─── Estratégias ─────────────────────────────────────────────────────────────

def _resolve_declared(step_spec: StepSpec) -> ToolResolution | None:
    """Estratégia 1: tools declaradas explicitamente."""
    if not step_spec.tools_required:
        return None

    declared = list(step_spec.tools_required)
    resolved = _merge_with_always(declared)
    return ToolResolution(
        tools=resolved,
        source="declared",
        tools_declared=declared,
        tools_inferred=[],
        audit={
            "tools_declared": declared,
            "tools_inferred": [],
            "tools_resolved": resolved,
            "inference_source": "declared",
        },
    )


def _resolve_keyword(step_spec: StepSpec) -> ToolResolution | None:
    """Estratégia 2: inferência por keyword na descrição."""
    desc_lower = step_spec.description.lower()
    inferred: list[str] = []

    for pattern, tools in KEYWORD_TOOL_MAP.items():
        if re.search(pattern, desc_lower):
            for t in tools:
                if t not in inferred:
                    inferred.append(t)

    if not inferred:
        return None

    resolved = _merge_with_always(inferred)
    return ToolResolution(
        tools=resolved,
        source="inferred_keyword",
        tools_declared=[],
        tools_inferred=inferred,
        audit={
            "tools_declared": [],
            "tools_inferred": inferred,
            "tools_resolved": resolved,
            "inference_source": "inferred_keyword",
        },
    )


async def _resolve_llm(
    step_spec: StepSpec,
    tier: ExecutionTier,
    model_router: ModelRouter,
) -> ToolResolution | None:
    """Estratégia 3: inferência via Haiku (cacheada 7 dias)."""
    cache_key = _cache_key(step_spec, tier)
    cached = _cache_get(cache_key)
    if cached is not None:
        log.debug("tool_router.llm.cache_hit", key=cache_key)
        inferred = cached
    else:
        available = sorted(KNOWN_BUILTIN_TOOLS)
        prompt = (
            f"Available tools: {json.dumps(available)}\n"
            f"Step description: {step_spec.description[:400]}\n\n"
            "Which tools are needed to complete this step? "
            'Reply ONLY with a JSON array of tool names from the available list. '
            "Example: [\"web_search\", \"write_file\"]"
        )
        try:
            response = await model_router.chat(
                system="You are a tool selector. Reply only with a JSON array of tool names.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                model="anthropic:claude-haiku-4-5",
            )
            raw = response.text.strip()
            start, end = raw.find("["), raw.rfind("]")
            if start == -1 or end == -1:
                log.warning("tool_router.llm.parse_error", raw=raw[:100])
                return None

            candidates: list[str] = json.loads(raw[start : end + 1])
            # Filtra para manter só tools realmente conhecidas
            inferred = [t for t in candidates if isinstance(t, str) and t in KNOWN_BUILTIN_TOOLS]
            _cache_set(cache_key, inferred)
            log.info("tool_router.llm.inferred", tools=inferred)
        except Exception as exc:
            log.warning("tool_router.llm.error", error=str(exc))
            return None

    if not inferred:
        return None

    resolved = _merge_with_always(inferred)
    return ToolResolution(
        tools=resolved,
        source="inferred_llm",
        tools_declared=[],
        tools_inferred=inferred,
        audit={
            "tools_declared": [],
            "tools_inferred": inferred,
            "tools_resolved": resolved,
            "inference_source": "inferred_llm",
        },
    )


def _resolve_fallback(tier: ExecutionTier) -> ToolResolution:
    """Estratégia 4: default seguro por tier."""
    if tier in (ExecutionTier.STRATEGIC, ExecutionTier.EPIC):
        # STRATEGIC/EPIC: acesso total — disciplina vem do prompt, não da ausência de tools
        resolved = sorted(KNOWN_BUILTIN_TOOLS)
    else:
        # INSTANT/FAST: conjunto conservador (sem LLM por custo)
        resolved = ["web_search", "read_file", "salvar_memoria", "ler_memoria"]

    resolved = _merge_with_always(resolved)
    return ToolResolution(
        tools=resolved,
        source="fallback_default",
        tools_declared=[],
        tools_inferred=[],
        audit={
            "tools_declared": [],
            "tools_inferred": [],
            "tools_resolved": resolved,
            "inference_source": "fallback_default",
        },
    )


# ─── Entrada pública ─────────────────────────────────────────────────────────

async def resolve_tools_for_step(
    step_spec: StepSpec,
    tier: ExecutionTier,
    *,
    model_router: ModelRouter | None = None,
) -> ToolResolution:
    """
    Resolve o conjunto de tools para um step, aplicando as 4 estratégias em ordem.

    1. declared   — step.tools_required não-vazio
    2. keyword    — keywords na descrição identificam tools
    3. inferred_llm — Haiku decide (só STRATEGIC/EPIC, cacheado 7 dias)
    4. fallback   — default seguro por tier

    Não faz I/O no banco — o chamador chama `log_routing_audit()` separado.
    """
    # 1. Declarado explicitamente
    res = _resolve_declared(step_spec)
    if res is not None:
        log.info(
            "tool_router.resolved",
            source="declared",
            tools=res.tools,
            tier=tier.value,
        )
        return res

    # 2. Inferência por keyword
    res = _resolve_keyword(step_spec)
    if res is not None:
        log.info(
            "tool_router.resolved",
            source="inferred_keyword",
            tools=res.tools,
            tier=tier.value,
        )
        return res

    # 3. Inferência via LLM (apenas STRATEGIC/EPIC para controlar custo)
    if tier in (ExecutionTier.STRATEGIC, ExecutionTier.EPIC) and model_router is not None:
        res = await _resolve_llm(step_spec, tier, model_router)
        if res is not None:
            log.info(
                "tool_router.resolved",
                source="inferred_llm",
                tools=res.tools,
                tier=tier.value,
            )
            return res

    # 4. Fallback
    res = _resolve_fallback(tier)
    log.info(
        "tool_router.resolved",
        source="fallback_default",
        tools=res.tools,
        tier=tier.value,
    )
    return res


async def log_routing_audit(
    step_id: UUID | None,
    tier: str,
    resolution: ToolResolution,
    db_pool: asyncpg.Pool,
) -> None:
    """
    Persiste decisão de routing em step_tool_routing.

    step_id pode ser None quando o chamador não tem referência ao step
    (ex: tasks que não vêm de missões). Nesse caso não registra — só missões
    têm step_tool_routing.
    """
    if step_id is None:
        return

    audit = resolution.audit
    try:
        await db_pool.execute(
            """
            INSERT INTO step_tool_routing
                (step_id, tier, tools_declared, tools_inferred, tools_resolved, inference_source)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6)
            """,
            step_id,
            tier,
            json.dumps(audit.get("tools_declared", []), ensure_ascii=False),
            json.dumps(audit.get("tools_inferred", []), ensure_ascii=False),
            json.dumps(audit.get("tools_resolved", []), ensure_ascii=False),
            audit.get("inference_source", "fallback_default"),
        )
    except Exception as exc:
        # Audit é best-effort — nunca deve travar a execução principal
        log.warning("tool_router.audit.failed", step_id=str(step_id), error=str(exc))


def validate_declared_tools(tools_required: list[str]) -> list[str]:
    """
    Retorna lista de tools declaradas que NÃO existem no registry builtin.
    Lista vazia = todas as tools declaradas estão disponíveis.

    Só deve ser chamado quando source=declared (tools explicitamente listadas).
    """
    return [t for t in tools_required if t not in KNOWN_BUILTIN_TOOLS]


# ─── Helpers privados ────────────────────────────────────────────────────────

def _merge_with_always(tools: list[str]) -> list[str]:
    """Garante que ALWAYS_TOOLS estejam presentes no set final, sem duplicatas."""
    result = list(tools)
    for t in ALWAYS_TOOLS:
        if t not in result:
            result.append(t)
    return result

