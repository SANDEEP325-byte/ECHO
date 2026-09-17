from typing import Any

from services.memory.conversation import ConversationMemory
from services.memory.facts import FactMemory
from services.memory.persistent import PersistentMemory
from services.memory.semantic import (
    DEFAULT_COLLECTION,
    SemanticMemory,
    semantic_memory,
)


class MemoryManager:
    """Central coordinator for ECHO's memory systems."""

    def __init__(
        self,
        conversation: ConversationMemory | None = None,
        persistent: PersistentMemory | None = None,
        facts: FactMemory | None = None,
        semantic: SemanticMemory | None = None,
    ) -> None:
        self.conversation = conversation or ConversationMemory()
        self.persistent = persistent or PersistentMemory()
        self.facts = facts or FactMemory()
        self.semantic = semantic if semantic is not None else semantic_memory

    # Conversation Memory

    def add_user_message(self, content: str) -> None:
        self.conversation.add_user_message(content)

    def add_assistant_message(self, content: str) -> None:
        self.conversation.add_assistant_message(content)

    def get_conversation(self):
        return self.conversation.get_messages()

    def clear_conversation(self) -> None:
        self.conversation.clear()

    # Persistent Memory

    def save_message(self, role: str, content: str) -> None:
        self.persistent.save_message(role, content)

    def get_recent_messages(
        self,
        limit: int = 20,
    ) -> list[dict[str, str]]:
        return self.persistent.get_recent_messages(limit)

    def clear_persistent_memory(self) -> None:
        self.persistent.clear()

    # Fact Memory

    def save_fact(self, key: str, value: str) -> None:
        self.facts.save_fact(key, value)

    def get_fact(self, key: str) -> str | None:
        return self.facts.get_fact(key)

    def get_all_facts(self) -> dict[str, str]:
        return self.facts.get_all_facts()

    def get_memory_context(self) -> str:
        return self.facts.get_context()

    def delete_fact(self, key: str) -> None:
        self.facts.delete_fact(key)

    def clear_facts(self) -> None:
        self.facts.clear()

    # Semantic Memory

    def add_semantic_memory(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        collection: str = DEFAULT_COLLECTION,
        memory_id: str | None = None,
        *,
        collection_name: str | None = None,
    ) -> str:
        coll = collection_name or collection
        if self.semantic is not None and hasattr(self.semantic, "add"):
            return self.semantic.add(
                content=content,
                metadata=metadata,
                collection_name=coll,
                memory_id=memory_id,
            )
        return ""

    def search_semantic_memory(
        self,
        query: str,
        limit: int = 5,
        collection: str = DEFAULT_COLLECTION,
        where: dict[str, Any] | None = None,
        *,
        collection_name: str | None = None,
    ) -> list[dict[str, Any]]:
        coll = collection_name or collection
        if self.semantic is not None and hasattr(self.semantic, "search"):
            try:
                return self.semantic.search(
                    query=query,
                    limit=limit,
                    collection_name=coll,
                    where=where,
                )
            except TypeError:
                return self.semantic.search(
                    query=query,
                    limit=limit,
                    collection_name=coll,
                )
        return []

    def get_semantic_memory(
        self,
        memory_id: str,
        collection: str = DEFAULT_COLLECTION,
        *,
        collection_name: str | None = None,
    ) -> dict[str, Any] | None:
        coll = collection_name or collection
        if self.semantic is not None and hasattr(self.semantic, "get"):
            return self.semantic.get(
                memory_id=memory_id,
                collection_name=coll,
            )
        return None

    def delete_semantic_memory(
        self,
        memory_id: str,
        collection: str = DEFAULT_COLLECTION,
        *,
        collection_name: str | None = None,
    ) -> bool:
        coll = collection_name or collection
        if self.semantic is not None and hasattr(self.semantic, "delete"):
            return self.semantic.delete(
                memory_id=memory_id,
                collection_name=coll,
            )
        return False

    def count_semantic_memory(
        self,
        collection: str = DEFAULT_COLLECTION,
        *,
        collection_name: str | None = None,
    ) -> int:
        coll = collection_name or collection
        if self.semantic is not None and hasattr(self.semantic, "count"):
            return self.semantic.count(collection_name=coll)
        return 0

    def clear_semantic_memory(
        self,
        collection: str | None = None,
        *,
        collection_name: str | None = None,
    ) -> None:
        coll = collection_name or collection
        if self.semantic is not None and hasattr(self.semantic, "clear"):
            self.semantic.clear(collection_name=coll)

    # Complete Memory

    def clear_all(self) -> None:
        self.clear_conversation()
        self.clear_persistent_memory()
        self.clear_facts()
        self.clear_semantic_memory()


memory_manager = MemoryManager()