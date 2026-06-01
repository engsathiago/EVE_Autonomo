"""
Teste de persistência cross-sessão.
Requer Postgres com schema aplicado + ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from agent.memory.store import MemoryStore

pytestmark = pytest.mark.integration

DSN = os.getenv("POSTGRES_DSN", "postgresql://agent:changeme@localhost:5432/agent")


@pytest_asyncio.fixture
async def store():
    s = await MemoryStore.create(dsn=DSN)
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_memory_persists_across_sessions(store: MemoryStore):
    """
    Simula duas sessões independentes.
    Fato salvo na sessão A deve ser recuperado na sessão B.
    """
    # Sessão A: salva um fato com ID único
    unique_tag = uuid.uuid4().hex[:8]
    project_fact = f"O projeto com tag {unique_tag} se chama OpenClaw e usa Python+Node"

    conv_a = await store.create_conversation(title="Sessão A")
    await store.save(
        content=project_fact,
        kind="fact",
        conversation_id=conv_a,
        importance=9,
        metadata={"session": "A"},
    )

    # Sessão B: busca sem saber o conversation_id da sessão A
    conv_b = await store.create_conversation(title="Sessão B")
    result = await store.search_hybrid(f"projeto com tag {unique_tag}", k=5)

    assert len(result.entries) >= 1
    top = result.entries[0]
    assert unique_tag in top.content
    assert top.importance == 9


@pytest.mark.asyncio
async def test_conversation_history_survives_restart(store: MemoryStore):
    """
    Mensagens gravadas em uma conversa podem ser recuperadas posteriormente.
    """
    conv_id = await store.create_conversation(title="Persistência de histórico")

    await store.append_message(conv_id, "user", "Qual é a capital do Brasil?")
    await store.append_message(conv_id, "assistant", "A capital do Brasil é Brasília.")
    await store.append_message(conv_id, "user", "E do Japão?")
    await store.append_message(conv_id, "assistant", "A capital do Japão é Tóquio.")

    # "reinicia" — recupera o histórico pelo ID
    msgs = await store.get_messages(conv_id)

    assert len(msgs) == 4
    assert msgs[0]["role"] == "user"
    assert "Brasil" in msgs[0]["content"]
    assert msgs[3]["role"] == "assistant"
    assert "Tóquio" in msgs[3]["content"]


@pytest.mark.asyncio
async def test_curator_decision_metadata_preserved(store: MemoryStore):
    """Metadados do Curator são preservados após save."""
    mem_id = await store.save(
        content="O usuário prefere respostas concisas e diretas",
        kind="preference",
        importance=8,
        metadata={"curator_reason": "preferência explícita de comunicação", "session": "test"},
    )

    # Busca de volta pelo conteúdo
    entries = await store.search_fts("respostas concisas", k=3)

    assert any(str(mem_id) == str(e.id) for e in entries)
    match = next(e for e in entries if str(e.id) == str(mem_id))
    assert match.metadata.get("curator_reason") is not None
    assert match.importance == 8
