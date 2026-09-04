from services.memory.database import get_connection, initialize_database
from services.memory.persistent import PersistentMemory
from services.memory.facts import FactMemory


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
    
def test_memory_returns_recent_messages_in_chronological_order(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_order.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    initialize_database()

    memory = PersistentMemory()

    memory.save_message("user", "Message 1")
    memory.save_message("assistant", "Message 2")
    memory.save_message("user", "Message 3")
    memory.save_message("assistant", "Message 4")

    messages = memory.get_recent_messages(limit=2)

    assert len(messages) == 2

    assert messages[0]["content"] == "Message 3"
    assert messages[1]["content"] == "Message 4"
    
def test_memory_can_clear_all_messages(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_clear.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    initialize_database()

    memory = PersistentMemory()

    memory.save_message("user", "Hello")
    memory.save_message("assistant", "Hello! How can I help?")

    assert len(memory.get_recent_messages()) == 2

    memory.clear()

    assert memory.get_recent_messages() == []
    
def test_fact_memory_can_save_and_retrieve_fact(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as databse
    
    test_db = tmp_path / "test_facts.db"
    
    monkeypatch.setattr(
        databse,
        "DB_PATH",
        test_db,
    )
    
    initialize_database()
    
    memory = FactMemory()
    
    memory.save_fact(
        "name",
        "Sandeep",
    )
    
    assert memory.get_fact("name") == "Sandeep"
    
def test_fact_memory_updates_existing_fact(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_facts_update.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    initialize_database()

    memory = FactMemory()

    memory.save_fact(
        "favorite_color",
        "Blue",
    )

    memory.save_fact(
        "favorite_color",
        "Black",
    )

    assert memory.get_fact("favorite_color") == "Black"
    
def test_fact_memory_can_retrieve_all_facts(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_facts_all.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    initialize_database()

    memory = FactMemory()

    memory.save_fact("favorite_color", "Black")
    memory.save_fact("name", "Sandeep")
    memory.save_fact("preferred_name", "Boss")

    facts = memory.get_all_facts()

    assert facts == {
        "favorite_color": "Black",
        "name": "Sandeep",
        "preferred_name": "Boss",
    }
    
def test_fact_memory_can_delete_fact(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_facts_delete.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    initialize_database()

    memory = FactMemory()

    memory.save_fact("name", "Sandeep")

    assert memory.get_fact("name") == "Sandeep"

    memory.delete_fact("name")

    assert memory.get_fact("name") is None
    
def test_fact_memory_can_clear_all_facts(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_facts_clear.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    initialize_database()

    memory = FactMemory()

    memory.save_fact("name", "Sandeep")
    memory.save_fact("preferred_name", "Boss")
    memory.save_fact("favorite_color", "Black")

    assert len(memory.get_all_facts()) == 3

    memory.clear()

    assert memory.get_all_facts() == {}
    
def test_memory_returns_only_recent_messages_with_limit(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_limit.db"

    monkeypatch.setattr(database, "DB_PATH", test_db)

    initialize_database()

    memory = PersistentMemory()

    memory.save_message("user", "Message 1")
    memory.save_message("assistant", "Message 2")
    memory.save_message("user", "Message 3")
    memory.save_message("assistant", "Message 4")

    messages = memory.get_recent_messages(limit=2)

    assert len(messages) == 2
    assert messages[0]["content"] == "Message 3"
    assert messages[1]["content"] == "Message 4"
    
def test_memory_can_clear_all_messages(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_clear.db"

    monkeypatch.setattr(database, "DB_PATH", test_db)

    initialize_database()

    memory = PersistentMemory()

    memory.save_message("user", "Hello")
    memory.save_message("assistant", "Hello! How can I help?")
    memory.save_message("user", "Tell me about Python.")

    assert len(memory.get_recent_messages()) == 3

    memory.clear()

    assert memory.get_recent_messages() == []