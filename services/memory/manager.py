from services.memory.conversation import ConversationMemory
from services.memory.facts import FactMemory
from services.memory.persistent import PersistentMemory


class MemoryManager:
    """Central coordinator for ECHO's memory systems."""
    
    def __init__(
        self,
        conversation: ConversationMemory | None = None,
        persistent: PersistentMemory | None = None,
        facts: FactMemory | None = None,
    ) -> None:
        self.conversation = conversation or ConversationMemory()
        self.persistent = persistent or PersistentMemory()
        self.facts = facts or FactMemory()
        
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
        
    # Complete Memory
    
    def clear_all(self) -> None:
        self.clear_conversation()
        self.clear_persistent_memory()
        self.clear_facts()
        
memory_manager = MemoryManager()