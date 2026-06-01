"""
Testes de integração do MemoryStore.
Requer Postgres rodando com POSTGRES_DSN configurado.
Marcar com pytest.mark.integration para excluir do CI sem banco.
"""

from __future__ import annotations

import os
import uuid

import pytest

from agent.memory.store import MemoryStore

pytestmark = pytest.mark.integration

DSN = os.getenv("POSTGRES_DSN", "postgresql://agent:changeme@localhost:5432/agent")


@pytest.fixture(scope="module")
async def store():
    s = await MemoryStore.create(dsn=DSN)
    yield s
    await s.close()


async def test_save_and_retrieve_vector(store: MemoryStore):
    """Salva textos em PT/EN e busca por sinônimo semântico."""
    await store.save("O usuário prefere Python para scripts de automação", kind="preference", importance=7)
    await store.save("O projeto usa FastAPI como framework web", kind="fact", importance=6)
    await store.save("The user likes automation and scripting", kind="fact", importance=5)

    results = await store.search_vector("linguagem de programação favorita para automação", k=3)

    assert len(results) >= 1
    top = results[0]
    assert top.score is not None
    assert top.score > 0.5
    assert top.content is not None


async def test_save_and_retrieve_fts(store: MemoryStore):
    """Salva texto com palavra específica e busca pelo termo exato."""
    unique_word = f"xyzterm{uuid.uuid4().hex[:6]}"
    await store.save(f"Configuração especial: {unique_word} é crítico para o sistema", importance=8)

    results = await store.search_fts(unique_word, k=5)

    assert len(results) >= 1
    assert any(unique_word in r.content for r in results)


async def test_hybrid_search_combines_both(store: MemoryStore):
    """Termo presente via FTS mas não óbvio vetorialmente aparece no top-K híbrido."""
    unique_word = f"bizterm{uuid.uuid4().hex[:6]}"
    await store.save(
        f"Referência técnica: {unique_word} é um identificador interno do projeto",
        kind="fact",
        importance=6,
    )

    result = await store.search_hybrid(unique_word, k=5)

    assert result.method == "hybrid"
    assert any(unique_word in e.content for e in result.entries)


async def test_unaccent(store: MemoryStore):
    """Salva com acento, busca sem acento — deve recuperar."""
    await store.save("A memória persistente é essencial para o agente", kind="fact", importance=5)

    results = await store.search_fts("memoria persistente", k=5)

    assert len(results) >= 1
    assert any("mem" in r.content.lower() for r in results)


async def test_filter_by_kind(store: MemoryStore):
    """Filtra por kind: busca por 'preference' não retorna 'fact'."""
    tag = uuid.uuid4().hex[:8]
    await store.save(f"Fato único {tag}: sistema usa Redis para pubsub", kind="fact", importance=5)
    await store.save(f"Preferência {tag}: o usuário prefere respostas curtas", kind="preference", importance=7)

    facts = await store.search_vector(tag, k=10, kind="fact")
    prefs = await store.search_vector(tag, k=10, kind="preference")

    assert all(e.kind == "fact" for e in facts)
    assert all(e.kind == "preference" for e in prefs)


async def test_conversation_lifecycle(store: MemoryStore):
    """Cria conversa, appenda mensagens e recupera histórico."""
    conv_id = await store.create_conversation(title="Teste", user_id="u1")
    assert conv_id is not None

    msg_id = await store.append_message(conv_id, "user", "olá, tudo bem?")
    assert isinstance(msg_id, int)

    await store.append_message(conv_id, "assistant", "Tudo ótimo! Como posso ajudar?")

    msgs = await store.get_messages(conv_id)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
