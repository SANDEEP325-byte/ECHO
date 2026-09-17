import pytest

from services.memory.semantic import (
    COLLECTION_KNOWLEDGE,
    COLLECTION_PROJECT_MEMORY,
    COLLECTION_USER_MEMORY,
    DefaultEmbeddingProvider,
    OllamaEmbeddingProvider,
    SemanticMemory,
)


@pytest.fixture
def temp_semantic_memory(tmp_path):
    """Provides an isolated SemanticMemory instance using a temporary directory."""
    return SemanticMemory(
        persist_path=tmp_path / "chroma",
        embedding_provider=DefaultEmbeddingProvider(dimension=64),
    )


def test_default_embedding_provider_deterministic():
    provider = DefaultEmbeddingProvider(dimension=64)
    v1 = provider.embed_query("ECHO memory architecture")
    v2 = provider.embed_query("ECHO memory architecture")
    assert v1 == v2
    assert len(v1) == 64
    # Length of non-empty text vector should be close to 1.0 (normalized)
    magnitude = sum(x * x for x in v1) ** 0.5
    assert 0.99 <= magnitude <= 1.01


def test_default_embedding_provider_empty_text():
    provider = DefaultEmbeddingProvider(dimension=32)
    vec = provider.embed_query("")
    assert vec == [0.0] * 32


def test_ollama_embedding_provider_fallback(monkeypatch):
    fallback = DefaultEmbeddingProvider(dimension=32)
    provider = OllamaEmbeddingProvider(
        host="http://non-existent-host:9999",
        model="qwen3:0.6b",
        fallback=fallback,
    )
    vec = provider.embed_query("test fallback")
    assert len(vec) == 32
    assert vec == fallback.embed_query("test fallback")


def test_semantic_memory_add_and_count(temp_semantic_memory):
    memory = temp_semantic_memory
    assert memory.count() == 0

    mem_id = memory.add("FastAPI is used for the web layer.")
    assert mem_id is not None
    assert len(mem_id) > 0
    assert memory.count() == 1


def test_semantic_memory_add_with_custom_id(temp_semantic_memory):
    memory = temp_semantic_memory
    mem_id = memory.add(
        content="SQLite handles structured relational facts.",
        memory_id="sqlite-fact-1",
        metadata={"category": "database", "priority": 10},
    )
    assert mem_id == "sqlite-fact-1"
    item = memory.get("sqlite-fact-1")
    assert item is not None
    assert item["id"] == "sqlite-fact-1"
    assert item["content"] == "SQLite handles structured relational facts."
    assert item["metadata"]["category"] == "database"
    assert item["metadata"]["priority"] == 10


def test_semantic_memory_add_empty_content_raises(temp_semantic_memory):
    memory = temp_semantic_memory
    with pytest.raises(ValueError, match="cannot be empty"):
        memory.add("")

    with pytest.raises(ValueError, match="cannot be empty"):
        memory.add("   ")


def test_semantic_memory_search(temp_semantic_memory):
    memory = temp_semantic_memory
    memory.add("Python is the primary language for ECHO development.")
    memory.add("React and TypeScript are used for modern frontends.")
    memory.add("ChromaDB is the local vector database.")

    results = memory.search("Python language", limit=2)
    assert len(results) >= 1
    assert any("Python" in r["content"] for r in results)
    assert "distance" in results[0]


def test_semantic_memory_search_empty_query(temp_semantic_memory):
    memory = temp_semantic_memory
    memory.add("Something to search.")
    assert memory.search("") == []
    assert memory.search("   ") == []


def test_semantic_memory_search_empty_collection(temp_semantic_memory):
    memory = temp_semantic_memory
    assert memory.search("anything") == []


def test_semantic_memory_get_nonexistent(temp_semantic_memory):
    memory = temp_semantic_memory
    assert memory.get("does-not-exist") is None


def test_semantic_memory_delete(temp_semantic_memory):
    memory = temp_semantic_memory
    mem_id = memory.add("Memory to be deleted.")
    assert memory.count() == 1

    deleted = memory.delete(mem_id)
    assert deleted is True
    assert memory.count() == 0
    assert memory.get(mem_id) is None

    # Deleting again returns False
    assert memory.delete(mem_id) is False


def test_semantic_memory_clear_collection(temp_semantic_memory):
    memory = temp_semantic_memory
    memory.add("Note 1", collection_name=COLLECTION_KNOWLEDGE)
    memory.add("Note 2", collection_name=COLLECTION_KNOWLEDGE)
    assert memory.count(COLLECTION_KNOWLEDGE) == 2

    memory.clear(COLLECTION_KNOWLEDGE)
    assert memory.count(COLLECTION_KNOWLEDGE) == 0


def test_semantic_memory_custom_collections(temp_semantic_memory):
    memory = temp_semantic_memory
    memory.add(
        "User prefers dark mode.",
        collection_name=COLLECTION_USER_MEMORY,
    )
    memory.add(
        "Project uses modular monolith architecture.",
        collection_name=COLLECTION_PROJECT_MEMORY,
    )

    assert memory.count(COLLECTION_USER_MEMORY) == 1
    assert memory.count(COLLECTION_PROJECT_MEMORY) == 1
    assert memory.count(COLLECTION_KNOWLEDGE) == 0

    user_results = memory.search("dark mode", collection_name=COLLECTION_USER_MEMORY)
    assert len(user_results) == 1
    assert "dark mode" in user_results[0]["content"]

    project_results = memory.search("modular monolith", collection_name=COLLECTION_PROJECT_MEMORY)
    assert len(project_results) == 1
    assert "modular monolith" in project_results[0]["content"]


def test_semantic_memory_clear_all(temp_semantic_memory):
    memory = temp_semantic_memory
    memory.add("Doc A", collection_name=COLLECTION_USER_MEMORY)
    memory.add("Doc B", collection_name=COLLECTION_PROJECT_MEMORY)

    memory.clear()
    assert memory.count(COLLECTION_USER_MEMORY) == 0
    assert memory.count(COLLECTION_PROJECT_MEMORY) == 0
