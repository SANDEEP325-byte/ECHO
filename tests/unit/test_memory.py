from services.memory.database import get_connection, initialize_database
from services.memory.persistent import PersistentMemory


def test_memory_can_save_and_retrieve(tmp_path, monkeypatch):
    import services.memory.database as database

    test_db = tmp_path / "test_memory.db"

    monkeypatch.setattr(database, "DB_PATH", test_db)

    initialize_database()

    memory = PersistentMemory()

    memory.save_message("user", "My favorite language is Python.")

    messages = memory.get_recent_messages()

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "My favorite language is Python."