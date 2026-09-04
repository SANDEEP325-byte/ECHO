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