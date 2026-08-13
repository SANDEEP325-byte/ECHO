from dataclasses import dataclass, field


@dataclass
class Message:
    role: str
    content: str


@dataclass
class ConversationMemory:
    messages: list[Message] = field(default_factory=list)

    def add_user_message(self, content: str) -> None:
        self.messages.append(
            Message(role="user", content=content)
        )

    def add_assistant_message(self, content: str) -> None:
        self.messages.append(
            Message(role="assistant", content=content)
        )

    def get_messages(self) -> list[Message]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()


conversation_memory = ConversationMemory()