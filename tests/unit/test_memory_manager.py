from services.memory.manager import MemoryManager


def test_memory_manager_can_save_and_retrieve_messages(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_manager.db"
    
    monkeypatch.setattr(database, "DB_PATH", test_db)
    
    database.initialize_database()
    
    manager = MemoryManager()
    
    manager.save_message(
        "user",
        "Hello ECHO",
    )
    
    messages = manager.get_recent_messages()
    
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello ECHO"
    
def test_memory_manager_can_save_and_retrieve_facts(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database
    
    test_db = tmp_path / "test_memory_manager_facts.db"
    
    monkeypatch.setattr(database, "DB_PATH", test_db)
    
    database.initialize_database()
    
    manager = MemoryManager()
    
    manager.save_fact(
        "name",
        "Sandeep",
    )
    
    assert manager.get_fact("name") == "Sandeep"
    
def test_memory_manager_can_generate_memory_context(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database
    
    test_db = tmp_path / "tesst_memory_manager_context.db"
    
    monkeypatch.setattr(database, "DB_PATH", test_db)
    
    database.initialize_database()
    
    manager = MemoryManager()
    
    manager.save_fact(
        "name",
        "Sandeep",
    )
    
    context = manager.get_memory_context()
    
    assert "Known facts about the user:" in context
    assert "name: Sandeep" in context
    
def test_memory_manager_can_handle_conversation_memory():
    manager = MemoryManager()
    
    manager.add_user_message("Hello")
    manager.add_assistant_message("Hello! How can I help?")
    
    messages = manager.get_conversation()
    
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello"
    assert messages[1].role == "assistant"
    
def test_memory_manager_can_clear_all_memory(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database
    
    test_db = tmp_path / "test_memory_manager_clear.db"
    
    monkeypatch.setattr(database, "DB_PATH", test_db)
    
    database.initialize_database()
    
    manager = MemoryManager()
    
    manager.save_message("user", "Hello")
    manager.save_fact("name", "Sandeep")
    
    manager.add_user_message("Hello")
    
    manager.clear_all()
    
    assert manager.get_recent_messages() == []
    assert manager.get_all_facts() == {}
    assert manager.get_conversation() == []
    
def test_memory_manager_delegates_fact_operations():
    class FakeFacts:
        def __init__(self):
            self.saved = None
            self.deleted = None

        def save_fact(self, key, value):
            self.saved = (key, value)

        def get_fact(self, key):
            return "test-value"

        def get_all_facts(self):
            return {"name": "Sandeep"}

        def get_context(self):
            return "Known facts about the user:\n- name: Sandeep"

        def delete_fact(self, key):
            self.deleted = key

        def clear(self):
            pass

    fake_facts = FakeFacts()

    manager = MemoryManager(
        facts=fake_facts,
    )

    manager.save_fact("name", "Sandeep")

    assert fake_facts.saved == ("name", "Sandeep")
    assert manager.get_fact("name") == "test-value"
    assert manager.get_all_facts() == {"name": "Sandeep"}
    assert "name: Sandeep" in manager.get_memory_context()

    manager.delete_fact("name")

    assert fake_facts.deleted == "name"
    
def test_memory_manager_delegates_persistent_operations():
    class FakePersistent:
        def __init__(self):
            self.saved = None
            self.cleared = False

        def save_message(self, role, content):
            self.saved = (role, content)

        def get_recent_messages(self, limit=20):
            return [
                {
                    "role": "user",
                    "content": "Hello ECHO",
                }
            ]

        def clear(self):
            self.cleared = True

    fake_persistent = FakePersistent()

    manager = MemoryManager(
        persistent=fake_persistent,
    )

    manager.save_message(
        "user",
        "Hello ECHO",
    )

    assert fake_persistent.saved == (
        "user",
        "Hello ECHO",
    )

    messages = manager.get_recent_messages()

    assert messages == [
        {
            "role": "user",
            "content": "Hello ECHO",
        }
    ]

    manager.clear_persistent_memory()

    assert fake_persistent.cleared is True
    
def test_memory_manager_delegates_conversation_operations():
    class FakeConversation:
        def __init__(self):
            self.messages = []
            self.cleared = False

        def add_user_message(self, content):
            self.messages.append(("user", content))

        def add_assistant_message(self, content):
            self.messages.append(("assistant", content))

        def get_messages(self):
            return self.messages

        def clear(self):
            self.messages.clear()
            self.cleared = True

    fake_conversation = FakeConversation()

    manager = MemoryManager(
        conversation=fake_conversation,
    )

    manager.add_user_message("Hello")

    manager.add_assistant_message(
        "Hello! How can I help?"
    )

    assert fake_conversation.messages == [
        ("user", "Hello"),
        ("assistant", "Hello! How can I help?"),
    ]

    assert manager.get_conversation() == [
        ("user", "Hello"),
        ("assistant", "Hello! How can I help?"),
    ]

    manager.clear_conversation()

    assert fake_conversation.cleared is True
    assert fake_conversation.messages == []
    
def test_memory_manager_clear_all_delegates_to_all_memory_systems():
    class FakeConversation:
        def __init__(self):
            self.cleared = False

        def add_user_message(self, content):
            pass

        def add_assistant_message(self, content):
            pass

        def get_messages(self):
            return []

        def clear(self):
            self.cleared = True

    class FakePersistent:
        def __init__(self):
            self.cleared = False

        def save_message(self, role, content):
            pass

        def get_recent_messages(self, limit=20):
            return []

        def clear(self):
            self.cleared = True

    class FakeFacts:
        def __init__(self):
            self.cleared = False

        def save_fact(self, key, value):
            pass

        def get_fact(self, key):
            return None

        def get_all_facts(self):
            return {}

        def get_context(self):
            return ""

        def delete_fact(self, key):
            pass

        def clear(self):
            self.cleared = True

    fake_conversation = FakeConversation()
    fake_persistent = FakePersistent()
    fake_facts = FakeFacts()

    manager = MemoryManager(
        conversation=fake_conversation,
        persistent=fake_persistent,
        facts=fake_facts,
    )

    manager.clear_all()

    assert fake_conversation.cleared is True
    assert fake_persistent.cleared is True
    assert fake_facts.cleared is True
    
def test_memory_manager_updates_existing_fact(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_manager_update.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    database.initialize_database()

    manager = MemoryManager()

    manager.save_fact("preferred_name", "Devil")

    assert manager.get_fact("preferred_name") == "Devil"

    manager.save_fact("preferred_name", "Boss")

    assert manager.get_fact("preferred_name") == "Boss"

    facts = manager.get_all_facts()

    assert facts == {
        "preferred_name": "Boss",
    }
    
def test_memory_manager_can_delete_specific_fact(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_manager_delete.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    database.initialize_database()

    manager = MemoryManager()

    manager.save_fact("name", "Sandeep")
    manager.save_fact("preferred_name", "Boss")
    manager.save_fact("favorite_color", "Black")

    manager.delete_fact("preferred_name")

    assert manager.get_fact("preferred_name") is None

    assert manager.get_fact("name") == "Sandeep"
    assert manager.get_fact("favorite_color") == "Black"
    
def test_memory_manager_can_delete_nonexistent_fact(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_manager_missing_fact.db"

    monkeypatch.setattr(
        database,
        "DB_PATH",
        test_db,
    )

    database.initialize_database()

    manager = MemoryManager()

    manager.delete_fact("unknown_fact")

    assert manager.get_fact("unknown_fact") is None
    assert manager.get_all_facts() == {}
    
def test_memory_manager_forwards_message_limit():
    class FakePersistent:
        def __init__(self):
            self.received_limit = None

        def save_message(self, role, content):
            pass

        def get_recent_messages(self, limit=20):
            self.received_limit = limit

            return [
                {
                    "role": "user",
                    "content": "Hello",
                }
            ]

        def clear(self):
            pass

    fake_persistent = FakePersistent()

    manager = MemoryManager(
        persistent=fake_persistent,
    )

    messages = manager.get_recent_messages(limit=5)

    assert fake_persistent.received_limit == 5
    assert messages == [
        {
            "role": "user",
            "content": "Hello",
        }
    ]
    
def test_memory_manager_delegates_memory_context():
    class FakeFacts:
        def save_fact(self, key, value):
            pass

        def get_fact(self, key):
            return None

        def get_all_facts(self):
            return {}

        def get_context(self):
            return "Known facts about the user:\n- name: Sandeep"

        def delete_fact(self, key):
            pass

        def clear(self):
            pass

    fake_facts = FakeFacts()

    manager = MemoryManager(
        facts=fake_facts,
    )

    context = manager.get_memory_context()

    assert context == (
        "Known facts about the user:\n"
        "- name: Sandeep"
    )
    
def test_memory_manager_can_delete_specific_fact(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_manager_delete_fact.db"

    monkeypatch.setattr(database, "DB_PATH", test_db)

    database.initialize_database()

    manager = MemoryManager()

    manager.save_fact(
        "name",
        "Sandeep",
    )

    manager.save_fact(
        "favorite_color",
        "Blue",
    )

    manager.delete_fact("name")

    assert manager.get_fact("name") is None
    assert manager.get_fact("favorite_color") == "Blue"
    
def test_memory_manager_updates_existing_fact(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_manager_update_fact.db"

    monkeypatch.setattr(database, "DB_PATH", test_db)

    database.initialize_database()

    manager = MemoryManager()

    manager.save_fact(
        "name",
        "Sandeep",
    )

    manager.save_fact(
        "name",
        "Boss",
    )

    assert manager.get_fact("name") == "Boss"

    facts = manager.get_all_facts()

    assert facts == {
        "name": "Boss",
    }
    
def test_memory_manager_returns_all_facts_in_sorted_order(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_manager_all_facts.db"

    monkeypatch.setattr(database, "DB_PATH", test_db)

    database.initialize_database()

    manager = MemoryManager()

    manager.save_fact("name", "Sandeep")
    manager.save_fact("preferred_name", "Boss")
    manager.save_fact("favorite_color", "Black")

    facts = manager.get_all_facts()

    assert list(facts.keys()) == [
        "favorite_color",
        "name",
        "preferred_name",
    ]

    assert facts["name"] == "Sandeep"
    assert facts["preferred_name"] == "Boss"
    assert facts["favorite_color"] == "Black"
    
def test_memory_manager_builds_context_from_multiple_facts(
    tmp_path,
    monkeypatch,
):
    import services.memory.database as database

    test_db = tmp_path / "test_memory_manager_multiple_context.db"

    monkeypatch.setattr(database, "DB_PATH", test_db)

    database.initialize_database()

    manager = MemoryManager()

    manager.save_fact("name", "Sandeep")
    manager.save_fact("preferred_name", "Boss")
    manager.save_fact("favorite_color", "Black")

    context = manager.get_memory_context()

    assert "Known facts about the user:" in context
    assert "- favorite_color: Black" in context
    assert "- name: Sandeep" in context
    assert "- preferred_name: Boss" in context


def test_memory_manager_delegates_semantic_operations():
    class FakeSemantic:
        def __init__(self):
            self.added = None
            self.searched = None
            self.got = None
            self.deleted = None
            self.counted = None
            self.cleared = None

        def add(self, content, metadata=None, collection_name="user_memory", memory_id=None):
            self.added = (content, metadata, collection_name, memory_id)
            return memory_id or "mem-1"

        def search(self, query, limit=5, collection_name="user_memory", where=None):
            self.searched = (query, limit, collection_name, where)
            return [{"id": "mem-1", "document": query, "metadata": {}, "distance": 0.1}]

        def get(self, memory_id, collection_name="user_memory"):
            self.got = (memory_id, collection_name)
            return {"id": memory_id, "document": "test doc", "metadata": {}}

        def delete(self, memory_id, collection_name="user_memory"):
            self.deleted = (memory_id, collection_name)
            return True

        def count(self, collection_name="user_memory"):
            self.counted = collection_name
            return 42

        def clear(self, collection_name=None):
            self.cleared = collection_name

    fake_sem = FakeSemantic()
    manager = MemoryManager(semantic=fake_sem)

    # Test add
    mid = manager.add_semantic_memory("User likes dark mode", {"tag": "ui"}, "user_memory", "custom-id")
    assert mid == "custom-id"
    assert fake_sem.added == ("User likes dark mode", {"tag": "ui"}, "user_memory", "custom-id")

    # Test search
    res = manager.search_semantic_memory("dark mode", limit=3, collection_name="user_memory")
    assert len(res) == 1
    assert fake_sem.searched == ("dark mode", 3, "user_memory", None)

    # Test get
    doc = manager.get_semantic_memory("custom-id", "user_memory")
    assert doc["id"] == "custom-id"
    assert fake_sem.got == ("custom-id", "user_memory")

    # Test delete
    assert manager.delete_semantic_memory("custom-id", "user_memory") is True
    assert fake_sem.deleted == ("custom-id", "user_memory")

    # Test count
    assert manager.count_semantic_memory("user_memory") == 42
    assert fake_sem.counted == "user_memory"

    # Test clear_semantic_memory
    manager.clear_semantic_memory("user_memory")
    assert fake_sem.cleared == "user_memory"


def test_memory_manager_clear_all_with_semantic():
    class FakeConversation:
        def __init__(self):
            self.cleared = False
        def clear(self):
            self.cleared = True

    class FakePersistent:
        def __init__(self):
            self.cleared = False
        def clear(self):
            self.cleared = True

    class FakeFacts:
        def __init__(self):
            self.cleared = False
        def clear(self):
            self.cleared = True

    class FakeSemantic:
        def __init__(self):
            self.cleared = False
        def clear(self, collection_name=None):
            self.cleared = True

    c = FakeConversation()
    p = FakePersistent()
    f = FakeFacts()
    s = FakeSemantic()

    manager = MemoryManager(conversation=c, persistent=p, facts=f, semantic=s)
    manager.clear_all()

    assert c.cleared is True
    assert p.cleared is True
    assert f.cleared is True
    assert s.cleared is True


def test_memory_manager_semantic_safe_when_no_semantic():
    class DummyNoSemantic:
        pass

    manager = MemoryManager(semantic=DummyNoSemantic())
    # Should not crash, returns safe fallback defaults
    assert manager.add_semantic_memory("test") == ""
    assert manager.search_semantic_memory("test") == []
    assert manager.get_semantic_memory("test") is None
    assert manager.delete_semantic_memory("test") is False
    assert manager.count_semantic_memory() == 0