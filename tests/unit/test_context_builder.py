from packages.interfaces.request import Request
from services.brain.context_builder import ContextBuilder


def test_context_builder_adds_request_metadata():
    builder = ContextBuilder()

    request = Request(
        user_input="Hello ECHO",
        source="chat",
        session_id="session-123",
    )

    result = builder.build(request)

    assert result.context["source"] == "chat"
    assert result.context["session_id"] == "session-123"


def test_context_builder_includes_recent_messages(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database
    from services.memory.persistent import PersistentMemory

    test_db = tmp_path / "context_messages.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    database.initialize_database()

    memory = PersistentMemory()

    memory.save_message(
        "user",
        "My favorite language is Python.",
    )

    builder = ContextBuilder()

    request = Request(
        user_input="What do you remember?"
    )

    result = builder.build(request)

    messages = result.context["recent_messages"]

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == (
        "My favorite language is Python."
    )


def test_context_builder_includes_facts(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database
    from services.memory.facts import FactMemory

    test_db = tmp_path / "context_facts.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    database.initialize_database()

    memory = FactMemory()

    memory.save_fact(
        "favorite_color",
        "blue",
    )

    builder = ContextBuilder()

    request = Request(
        user_input="What is my favorite color?"
    )

    result = builder.build(request)

    facts = result.context["facts"]

    assert facts["favorite_color"] == "blue"


def test_context_builder_returns_empty_sources_when_no_memory(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "empty_context.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    database.initialize_database()

    builder = ContextBuilder()

    request = Request(user_input="Hello")

    result = builder.build(request)

    assert result.context["recent_messages"] == []
    assert result.context["facts"] == {}


def test_context_builder_preserves_request_id():
    builder = ContextBuilder()

    request = Request(user_input="Hello")
    request_id = request.request_id

    result = builder.build(request)

    assert result.request_id == request_id
    
def test_context_builder_uses_memory_manager(
    monkeypatch,
):
    from services.memory.manager import MemoryManager

    class FakeMemoryManager:
        def get_recent_messages(self, limit=20):
            assert limit == 6
            return [
                {
                    "role": "user",
                    "content": "Remember this.",
                }
            ]

        def get_all_facts(self):
            return {
                "favorite_color": "blue",
            }

    builder = ContextBuilder()

    request = Request(
        user_input="What do you remember?"
    )

    result = builder.build(
        request,
        memory_manager=FakeMemoryManager(),
    )

    assert result.context["recent_messages"] == [
        {
            "role": "user",
            "content": "Remember this.",
        }
    ]

    assert result.context["facts"] == {
        "favorite_color": "blue",
    }


def test_context_builder_populates_semantic_memories():
    class FakeMemoryManagerWithSemantic:
        def __init__(self):
            self.last_query = None
            self.last_limit = None

        def get_recent_messages(self, limit=20):
            return []

        def get_all_facts(self):
            return {}

        def search_semantic_memory(self, query, limit=5, **kwargs):
            self.last_query = query
            self.last_limit = limit
            return [
                {
                    "id": "mem-1",
                    "document": "User prefers concise answers",
                    "metadata": {"source": "note"},
                    "distance": 0.05,
                }
            ]

    fake_manager = FakeMemoryManagerWithSemantic()
    builder = ContextBuilder()
    request = Request(user_input="How should you answer me?")

    result = builder.build(request, memory_manager=fake_manager)

    assert fake_manager.last_query == "How should you answer me?"
    assert fake_manager.last_limit == 3
    assert len(result.context["semantic_memories"]) == 1
    assert result.context["semantic_memories"][0]["id"] == "mem-1"
    assert result.context["semantic_memories"][0]["document"] == "User prefers concise answers"


def test_context_builder_handles_semantic_search_exception_gracefully():
    class BrokenSemanticMemoryManager:
        def get_recent_messages(self, limit=20):
            return []

        def get_all_facts(self):
            return {}

        def search_semantic_memory(self, query, limit=5, **kwargs):
            raise RuntimeError("ChromaDB service temporarily unavailable")

    builder = ContextBuilder()
    request = Request(user_input="Hello ECHO")

    result = builder.build(request, memory_manager=BrokenSemanticMemoryManager())

    assert result.context["semantic_memories"] == []