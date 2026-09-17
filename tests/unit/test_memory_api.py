import pytest
from fastapi.testclient import TestClient

from services.api.main import app
from services.memory.manager import memory_manager
from services.memory.semantic import (
    DefaultEmbeddingProvider,
    SemanticMemory,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Provides a TestClient with isolated memory manager and Chroma database."""
    # Ensure memory_manager uses an isolated temporary semantic memory store
    temp_semantic = SemanticMemory(
        persist_path=tmp_path / "api_chroma",
        embedding_provider=DefaultEmbeddingProvider(dimension=32),
    )
    monkeypatch.setattr(memory_manager, "semantic", temp_semantic)

    # Clean initial state
    memory_manager.clear_all()

    with TestClient(app) as test_client:
        yield test_client

    # Clean up after test
    memory_manager.clear_all()


# Fact API Tests

def test_api_save_and_get_fact(client):
    # Create fact
    response = client.post(
        "/memory/facts",
        json={"key": "favorite_food", "value": "Biryani"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["key"] == "favorite_food"
    assert data["value"] == "Biryani"

    # Get single fact
    get_res = client.get("/memory/facts/favorite_food")
    assert get_res.status_code == 200
    assert get_res.json()["value"] == "Biryani"

    # Get all facts
    all_res = client.get("/memory/facts")
    assert all_res.status_code == 200
    assert all_res.json()["facts"]["favorite_food"] == "Biryani"


def test_api_get_fact_not_found(client):
    response = client.get("/memory/facts/unknown_key")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_api_save_fact_empty_key_or_value(client):
    # Empty key
    res1 = client.post("/memory/facts", json={"key": "", "value": "val"})
    assert res1.status_code == 422

    # Empty value
    res2 = client.post("/memory/facts", json={"key": "k", "value": ""})
    assert res2.status_code == 422


def test_api_delete_and_clear_facts(client):
    client.post("/memory/facts", json={"key": "k1", "value": "v1"})
    client.post("/memory/facts", json={"key": "k2", "value": "v2"})

    # Delete single fact
    del_res = client.delete("/memory/facts/k1")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Verify k1 is deleted but k2 remains
    assert client.get("/memory/facts/k1").status_code == 404
    assert client.get("/memory/facts/k2").status_code == 200

    # Clear all facts
    clear_res = client.delete("/memory/facts")
    assert clear_res.status_code == 200
    assert client.get("/memory/facts").json()["facts"] == {}


# Message API Tests

def test_api_messages_and_conversation(client):
    memory_manager.save_message("user", "Hello ECHO")
    memory_manager.save_message("assistant", "Hello! How can I assist you?")

    # Get recent messages
    res = client.get("/memory/messages?limit=10")
    assert res.status_code == 200
    messages = res.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"

    # Invalid limit (< 1 or > 100)
    assert client.get("/memory/messages?limit=0").status_code == 422
    assert client.get("/memory/messages?limit=101").status_code == 422

    # Clear persistent messages
    clear_res = client.delete("/memory/messages")
    assert clear_res.status_code == 200
    assert client.get("/memory/messages").json()["messages"] == []


def test_api_conversation_memory(client):
    memory_manager.add_user_message("Session question")
    memory_manager.add_assistant_message("Session answer")

    res = client.get("/memory/conversation")
    assert res.status_code == 200
    msgs = res.json()["messages"]
    assert len(msgs) == 2

    # Clear conversation memory
    del_res = client.delete("/memory/conversation")
    assert del_res.status_code == 200
    assert client.get("/memory/conversation").json()["messages"] == []


# Semantic Memory API Tests

def test_api_semantic_memory_lifecycle(client):
    # Add semantic memory
    post_res = client.post(
        "/memory/semantic",
        json={
            "content": "ECHO architecture is designed as a modular monolith.",
            "collection": "knowledge",
            "metadata": {"source": "docs", "priority": 1},
        },
    )
    assert post_res.status_code == 201
    item_id = post_res.json()["id"]
    assert item_id is not None

    # Search semantic memory
    search_res = client.post(
        "/memory/semantic/search",
        json={
            "query": "modular monolith architecture",
            "limit": 3,
            "collection": "knowledge",
        },
    )
    assert search_res.status_code == 200
    results = search_res.json()["results"]
    assert len(results) >= 1
    assert "modular monolith" in results[0]["content"]

    # Delete semantic memory item
    del_res = client.delete(f"/memory/semantic/{item_id}?collection=knowledge")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Delete again returns 404
    del_again = client.delete(f"/memory/semantic/{item_id}?collection=knowledge")
    assert del_again.status_code == 404


def test_api_semantic_validation_errors(client):
    # Empty content
    res1 = client.post("/memory/semantic", json={"content": ""})
    assert res1.status_code == 422

    # Empty search query
    res2 = client.post("/memory/semantic/search", json={"query": ""})
    assert res2.status_code == 422


def test_api_semantic_clear(client):
    client.post(
        "/memory/semantic",
        json={"content": "Note 1", "collection": "notes"},
    )
    assert len(client.post("/memory/semantic/search", json={"query": "Note", "collection": "notes"}).json()["results"]) == 1

    clear_res = client.delete("/memory/semantic?collection=notes")
    assert clear_res.status_code == 200
    assert len(client.post("/memory/semantic/search", json={"query": "Note", "collection": "notes"}).json()["results"]) == 0


def test_api_full_memory_wipe(client):
    # Populate facts, messages, and semantic memory
    client.post("/memory/facts", json={"key": "k", "value": "v"})
    memory_manager.save_message("user", "Hello")
    client.post("/memory/semantic", json={"content": "Some doc"})

    # Wipe
    wipe_res = client.post("/memory/wipe")
    assert wipe_res.status_code == 200
    assert wipe_res.json()["success"] is True

    # Verify everything is empty
    assert client.get("/memory/facts").json()["facts"] == {}
    assert client.get("/memory/messages").json()["messages"] == []
    assert len(client.post("/memory/semantic/search", json={"query": "doc"}).json()["results"]) == 0
