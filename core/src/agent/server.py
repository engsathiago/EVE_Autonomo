import json
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import __version__
from agent.api.approvals import make_approvals_router_full
from agent.api.cron import make_cron_router
from agent.api.critic import make_critic_router
from agent.api.loop import make_loop_router
from agent.api.messages import make_messages_router
from agent.api.missions import make_missions_router
from agent.api.reflexive_memory import make_reflexive_memory_router
from agent.api.skills import make_skills_router
from agent.api.tasks import make_tasks_router
from agent.approvals.manager import ApprovalManager
from agent.approvals.scheduler import ApprovalScheduler
from agent.channels.dispatcher import OutboundDispatcher
from agent.config import build_model_router, get_settings
from agent.core import AIAgent
from agent.events import AgentEvent
from agent.memory.compressor import ContextCompressor
from agent.memory.curator import Curator
from agent.memory.store import MemoryStore
from agent.observability import configure_logging
from agent.skills.manager import SkillManager
from agent.tools.registry import ToolRegistry, register_builtin, register_memory_tools
from agent.transports import AnthropicTransport

_registry: ToolRegistry | None = None
_memory_store: MemoryStore | None = None
_curator: Curator | None = None
_compressor: ContextCompressor | None = None
_skill_manager: SkillManager | None = None
_model_router = None
_approval_manager: ApprovalManager | None = None
_approval_scheduler: ApprovalScheduler | None = None
_dispatcher: OutboundDispatcher | None = None
_redis_client: aioredis.Redis | None = None

# Phase 6 globals
_task_store = None
_cron_store = None
_cron_worker = None
_orchestrator = None
_subagent_pool = None

# Phase 7 globals
_mission_store = None
_reflexive_memory = None
_critic = None
_planner = None
_reflector = None
_autonomous_loop = None

# Phase 9 globals
_skill_registry = None
_skill_runner = None
_skill_promoter = None
_skill_synthesizer = None
_skill_decay_manager = None

_CURATOR_ENABLED = os.getenv("MEMORY_CURATOR_ENABLED", "true").lower() != "false"
_ORCHESTRATOR_ENABLED = os.getenv("ORCHESTRATOR_ENABLED", "true").lower() != "false"
_SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() != "false"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _registry, _memory_store, _curator, _compressor
    global _skill_manager, _model_router, _approval_manager
    global _approval_scheduler, _dispatcher, _redis_client
    global _task_store, _cron_store, _cron_worker, _orchestrator, _subagent_pool
    global _mission_store, _reflexive_memory, _critic, _planner, _reflector, _autonomous_loop
    global _skill_registry, _skill_runner, _skill_promoter, _skill_synthesizer, _skill_decay_manager

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    # ── Fase 0-5: componentes existentes ─────────────────────────────────────
    _memory_store = await MemoryStore.create()
    _curator = Curator() if _CURATOR_ENABLED else None
    _compressor = ContextCompressor()

    _registry = ToolRegistry()
    register_builtin(_registry)
    register_memory_tools(_registry, _memory_store)

    _model_router = build_model_router(settings, db_pool=_memory_store._pool)

    _redis_client = aioredis.from_url(settings.redis.url, decode_responses=True)
    _dispatcher = OutboundDispatcher(_redis_client)

    _approval_manager = ApprovalManager(
        db_pool=_memory_store._pool,
        timeout_s=settings.approvals.default_timeout_s,
    )

    _skill_manager = SkillManager(
        skills_dir=Path(settings.skills.skills_dir),
        transport=AnthropicTransport(model=settings.anthropic.planner_model),
        memory_store=_memory_store,
        cache_dir=Path(settings.skills.skills_embedding_cache_dir),
        model_router=_model_router,
        approval_manager=_approval_manager,
    )
    await _skill_manager.load_all()

    _approval_scheduler = ApprovalScheduler(
        _approval_manager,
        interval_s=settings.approvals.scheduler_interval_s,
    )
    _approval_scheduler.start()

    # ── Fase 6: cron + subagentes + orchestrator ──────────────────────────────
    if _ORCHESTRATOR_ENABLED:
        from agent.tasks.store import TaskStore
        from agent.scheduler.store import CronStore
        from agent.subagents.pool import SubagentPool
        from agent.orchestrator.tiers import TierClassifier
        from agent.orchestrator.router import Orchestrator

        _task_store = TaskStore(_memory_store._pool)
        _cron_store = CronStore(_memory_store._pool)

        _subagent_pool = SubagentPool(
            model_router=_model_router,
            task_store=_task_store,
            approval_manager=_approval_manager,
            max_concurrent=settings.subagents.max_concurrent_global,
            hard_timeout_s=settings.subagents.hard_timeout_seconds,
        )

        classifier = TierClassifier(
            model_router=_model_router,
            model=settings.orchestrator.classifier_model,
            max_tokens=settings.orchestrator.classifier_max_tokens,
            cache_ttl_s=settings.orchestrator.tier_cache_ttl_s,
        )

        _orchestrator = Orchestrator(
            model_router=_model_router,
            task_store=_task_store,
            subagent_pool=_subagent_pool,
            classifier=classifier,
            memory_store=_memory_store,
            curator=_curator,
            compressor=_compressor,
            skill_manager=_skill_manager,
            approval_manager=_approval_manager,
            fast_max_iterations=settings.orchestrator.fast_max_iterations,
            strategic_max_iterations=settings.orchestrator.strategic_max_iterations,
            epic_max_parallel=settings.orchestrator.epic_max_parallel,
            epic_max_iterations_per_child=settings.orchestrator.epic_max_iterations_per_child,
        )

        if _SCHEDULER_ENABLED and settings.scheduler.enabled:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

            from agent.scheduler.worker import CronWorker

            # APScheduler usa SQLAlchemy síncrono — requer URL sem +asyncpg
            db_url = os.getenv("POSTGRES_DSN", "postgresql://agent:agent@postgres:5432/agent")
            sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

            scheduler = AsyncIOScheduler(
                jobstores={"default": SQLAlchemyJobStore(url=sync_url)},
                timezone=settings.scheduler.timezone,
                job_defaults={
                    "coalesce": True,
                    "max_instances": settings.scheduler.max_instances,
                    "misfire_grace_time": settings.scheduler.misfire_grace_seconds,
                },
            )

            _cron_worker = CronWorker(
                scheduler=scheduler,
                cron_store=_cron_store,
                task_store=_task_store,
                orchestrator=_orchestrator,
                timezone=settings.scheduler.timezone,
            )
            await _cron_worker.start()

    # ── Fase 7: missões + critic + loop autônomo ──────────────────────────────
    if _ORCHESTRATOR_ENABLED:
        from agent.missions.store import MissionStore
        from agent.memory.reflexive import ReflexiveMemory
        from agent.critic.critic import Critic
        from agent.missions.planner import MissionPlanner
        from agent.missions.reflector import MissionReflector
        from agent.autonomous.loop import AutonomousLoop

        _mission_store = MissionStore(_memory_store._pool)
        _reflexive_memory = ReflexiveMemory(_memory_store._pool)

        _critic = Critic(
            model_router=_model_router,
            medium_model=settings.critic.medium_model,
            primary_model=settings.critic.primary_model,
            cost_threshold_usd=settings.critic.cost_threshold_usd,
        ) if settings.critic.enabled else None

        _planner = MissionPlanner(
            model_router=_model_router,
            reflexive_memory=_reflexive_memory,
            model=settings.missions.planner_model,
        )

        _reflector = MissionReflector(
            model_router=_model_router,
            mission_store=_mission_store,
            reflexive_memory=_reflexive_memory,
            model=settings.missions.reflector_model,
        )

        _autonomous_loop = AutonomousLoop(
            mission_store=_mission_store,
            orchestrator=_orchestrator,
            task_store=_task_store,
            critic=_critic,
            reflector=_reflector,
            planner=_planner,
            db_pool=_memory_store._pool,
        )

        if (
            _SCHEDULER_ENABLED
            and settings.scheduler.enabled
            and settings.missions.loop_enabled
            and _cron_worker is not None
        ):
            await _autonomous_loop.start(_cron_worker._scheduler)

        # Registra rotas REST da F7 — globals já inicializados acima
        if _mission_store and _planner and _reflector:
            app.include_router(make_missions_router(_mission_store, _planner, _reflector))
        if _critic and _memory_store:
            app.include_router(make_critic_router(_critic, _memory_store._pool))
        if _reflexive_memory:
            app.include_router(make_reflexive_memory_router(_reflexive_memory))
        if _autonomous_loop and _mission_store:
            app.include_router(make_loop_router(_autonomous_loop, _mission_store))

    # ── Fase 9: skills auto-geradas ───────────────────────────────────────────
    _project_root = Path(__file__).parents[4]
    _skills_root = _project_root / "skills"
    _active_dir = _skills_root / "_active"
    _pending_dir = _skills_root / "_pending"
    _rejected_dir = _skills_root / "_rejected"
    _archive_dir = _skills_root / "_archive"
    for _d in [_active_dir, _pending_dir, _rejected_dir, _archive_dir]:
        _d.mkdir(parents=True, exist_ok=True)

    try:
        from agent.skills.registry import SkillRegistry as SkillRegistryF9
        from agent.skills.runner import SkillRunner as SkillRunnerF9
        from agent.skills.promoter import SkillPromoter
        from agent.skills.synthesizer import SkillSynthesizer
        from agent.skills.decay import SkillDecayManager
        from agent.api.skills import make_skills_router
        from agent.tools.exec_tool import exec_tool

        _skill_registry = SkillRegistryF9(_memory_store._pool)
        _skill_runner = SkillRunnerF9(
            registry=_skill_registry,
            skills_active_dir=_active_dir,
            exec_tool_fn=exec_tool,
        )
        _skill_promoter = SkillPromoter(
            registry=_skill_registry,
            pending_dir=_pending_dir,
            active_dir=_active_dir,
            rejected_dir=_rejected_dir,
            critic=_critic,
        )
        _skill_synthesizer = SkillSynthesizer(
            db_pool=_memory_store._pool,
            output_dir=_pending_dir,
            model_router=_model_router,
        )
        _skill_decay_manager = SkillDecayManager(
            registry=_skill_registry,
            active_dir=_active_dir,
            archive_dir=_archive_dir,
        )

        # Job de decay diário às 3h
        if _SCHEDULER_ENABLED and _cron_worker is not None:
            _cron_worker._scheduler.add_job(
                _run_skill_decay,
                "cron",
                hour=3,
                minute=0,
                id="skill_decay_daily",
                replace_existing=True,
            )

        app.include_router(make_skills_router(
            registry=_skill_registry,
            runner=_skill_runner,
            promoter=_skill_promoter,
            synthesizer=_skill_synthesizer,
        ))
    except Exception as _exc:
        import logging
        logging.getLogger(__name__).warning("skill_registry_init_failed: %s", _exc)

    yield

    # ── Shutdown (ordem inversa) ──────────────────────────────────────────────
    if _cron_worker:
        _cron_worker.shutdown(wait=False)
    if _approval_scheduler:
        await _approval_scheduler.stop()
    if _redis_client:
        await _redis_client.aclose()
    if _memory_store:
        await _memory_store.close()


async def _run_skill_decay() -> None:
    if _skill_decay_manager is not None:
        await _skill_decay_manager.scan()


app = FastAPI(title="agent-core", version=__version__, lifespan=lifespan)

# Rotas registradas em escopo de módulo — lambdas lêem globals no momento da request
app.include_router(
    make_messages_router(lambda: {
        "memory_store": _memory_store,
        "skill_manager": _skill_manager,
        "model_router": _model_router,
        "curator": _curator,
        "compressor": _compressor,
        "settings": get_settings(),
        "orchestrator": _orchestrator,
        "task_store": _task_store,
    })
)
app.include_router(
    make_approvals_router_full(
        get_approval_manager=lambda: _approval_manager,
        get_skill_manager=lambda: _skill_manager,
    )
)
app.include_router(
    make_cron_router(
        get_cron_store=lambda: _cron_store,
        get_cron_worker=lambda: _cron_worker,
        get_model_router=lambda: _model_router,
    )
)
app.include_router(
    make_tasks_router(
        get_task_store=lambda: _task_store,
        get_orchestrator=lambda: _orchestrator,
    )
)


def _get_registry() -> ToolRegistry:
    if _registry is None:
        raise RuntimeError("registry não inicializado")
    return _registry


def _get_store() -> MemoryStore:
    if _memory_store is None:
        raise RuntimeError("memory_store não inicializado")
    return _memory_store


def _get_skill_manager() -> SkillManager:
    if _skill_manager is None:
        raise RuntimeError("skill_manager não inicializado")
    return _skill_manager


# ── Request/Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    text: str
    iterations: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    duration_s: float
    conversation_id: str
    tier: str | None = None


class ToolInfo(BaseModel):
    name: str
    description: str
    requires_confirmation: bool


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "ok": True,
        "version": __version__,
        "model": settings.agent.default_model,
        "orchestrator": _orchestrator is not None,
        "scheduler": _cron_worker is not None,
        "missions": _mission_store is not None,
        "autonomous_loop": _autonomous_loop is not None,
    }


@app.get("/metrics", response_class=__import__("fastapi").responses.PlainTextResponse)
async def prometheus_metrics() -> str:
    from agent.metrics.phase_7 import metrics
    if _mission_store:
        active = await _mission_store.list_active()
        metrics.missions_active = len(active)
    return metrics.prometheus_text()


@app.get("/api/tools")
async def list_tools() -> dict[str, object]:
    registry = _get_registry()
    tools = []
    for name in registry.names():
        tool = registry.get(name)
        if tool:
            tools.append(ToolInfo(
                name=tool.name,
                description=tool.description,
                requires_confirmation=tool.requires_confirmation,
            ))
    return {"tools": [t.model_dump() for t in tools]}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    settings = get_settings()
    store = _get_store()

    if req.conversation_id:
        conversation_id = UUID(req.conversation_id)
        await store.ensure_conversation(conversation_id)
        history_rows = await store.get_messages(conversation_id, limit=50)
        conversation_history = _rows_to_messages(history_rows)
    else:
        conversation_id = await store.create_conversation()
        conversation_history = []

    # Roteamento via Orchestrator quando disponível
    if _orchestrator is not None and _task_store is not None:
        from agent.tasks.task import Task, TaskSource
        task = Task(
            content=req.message,
            source=TaskSource.API,
            channel_ref={"conversation_id": str(conversation_id)},
        )
        await _task_store.create(task)
        result = await _orchestrator.route(task)
        return ChatResponse(
            text=result.final_text,
            iterations=result.iterations,
            input_tokens=result.total_input_tokens,
            output_tokens=result.total_output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            duration_s=result.duration_s,
            conversation_id=str(conversation_id),
            tier=task.tier,
        )

    # Fallback: fluxo Fase 5 direto (sem orchestrator)
    registry = ToolRegistry()
    register_builtin(registry)
    register_memory_tools(registry, store, conversation_id)

    planner = AnthropicTransport(model=settings.anthropic.planner_model)
    reflector = AnthropicTransport(model=settings.anthropic.reflector_model)

    agent = AIAgent(
        transport=planner,
        tool_registry=registry,
        reflector_transport=reflector,
        memory_store=store,
        curator=_curator,
        compressor=_compressor,
        conversation_id=conversation_id,
        skill_manager=_get_skill_manager(),
        model_router=_model_router,
    )
    result = await agent.run(goal=req.message, conversation_history=conversation_history)

    return ChatResponse(
        text=result.final_text,
        iterations=result.iterations,
        input_tokens=result.total_input_tokens,
        output_tokens=result.total_output_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        duration_s=result.duration_s,
        conversation_id=str(conversation_id),
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    settings = get_settings()
    store = _get_store()

    if req.conversation_id:
        conversation_id = UUID(req.conversation_id)
        history_rows = await store.get_messages(conversation_id, limit=50)
        conversation_history = _rows_to_messages(history_rows)
    else:
        conversation_id = await store.create_conversation()
        conversation_history = []

    registry = ToolRegistry()
    register_builtin(registry)
    register_memory_tools(registry, store, conversation_id)

    planner = AnthropicTransport(model=settings.anthropic.planner_model)
    reflector = AnthropicTransport(model=settings.anthropic.reflector_model)

    agent = AIAgent(
        transport=planner,
        tool_registry=registry,
        reflector_transport=reflector,
        memory_store=store,
        curator=_curator,
        compressor=_compressor,
        conversation_id=conversation_id,
        skill_manager=_get_skill_manager(),
        model_router=_model_router,
    )

    async def _event_stream() -> AsyncGenerator[str, None]:
        import asyncio
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def enqueue(event: AgentEvent) -> None:
            await queue.put(event)

        async def run_agent() -> None:
            await agent.run(
                goal=req.message,
                on_event=enqueue,
                conversation_history=conversation_history,
            )
            await queue.put(None)

        task = asyncio.create_task(run_agent())

        yield f"data: {json.dumps({'type': 'conversation_id', 'data': {'id': str(conversation_id)}}, ensure_ascii=False)}\n\n"

        while True:
            event = await queue.get()
            if event is None:
                break
            data = json.dumps(event.model_dump(), ensure_ascii=False)
            yield f"data: {data}\n\n"

        await task

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rows_to_messages(rows: list[dict]) -> list[dict]:
    messages = []
    for row in rows:
        role = row["role"]
        content = row["content"]
        if role in ("user", "assistant", "system"):
            tool_calls_raw = row.get("tool_calls")
            if role == "assistant" and tool_calls_raw:
                tool_calls = json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
                messages.append({"role": role, "content": content, "tool_calls": tool_calls})
            else:
                messages.append({"role": role, "content": content})
    return messages
