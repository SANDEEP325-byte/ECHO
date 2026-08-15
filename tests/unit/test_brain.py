import pytest

from services.brain.brain import ECHOBrain

class FakeGateway:
    async def generate(self, messages, tool_result=None):
        if tool_result is not None:
            return f"Calculator result: {tool_result}"

        return "Hello! I am ECHO."

class FakeToolRouter:
    def should_use_calculator(self, message: str) -> bool:
        return "25 * 4" in message

    def execute_calculator(self, message: str) -> int:
        return 100

class FakeMemory:
    def __init__(self):
        self.messages = []

    def get_recent_messages(self, limit=6):
        return self.messages[-limit:]

    def save_message(self, role: str, content: str):
        self.messages.append(
            {
                "role": role,
                "content": content,
            }
        )

@pytest.mark.anyio
async def test_brain_handles_greeting(monkeypatch):
    brain = ECHOBrain()

    fake_gateway = FakeGateway()
    fake_tool_router = FakeToolRouter()
    fake_memory = FakeMemory()

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway",
        fake_gateway,
    )

    monkeypatch.setattr(
        "services.brain.brain.tool_router",
        fake_tool_router,
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    response = await brain.process("Hello ECHO")

    assert response == (
        "Hello! I'm ECHO, your personal AI assistant. "
        "How can I help you today? 😊"
    )

    assert fake_memory.messages == [
        {
            "role": "user",
            "content": "Hello ECHO",
        },
        {
            "role": "assistant",
            "content": ("Hello! I'm ECHO, your personal AI assistant. "
            "How can I help you today? 😊"
            ),
        },
    ]


@pytest.mark.anyio
async def test_brain_uses_calculator(monkeypatch):
    brain = ECHOBrain()

    fake_gateway = FakeGateway()
    fake_tool_router = FakeToolRouter()
    fake_memory = FakeMemory()

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway",
        fake_gateway,
    )

    monkeypatch.setattr(
        "services.brain.brain.tool_router",
        fake_tool_router,
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    response = await brain.process("What is 25 * 4?")

    assert response == "Calculator result: 100"

    assert fake_memory.messages[-1] == {
        "role": "assistant",
        "content": "Calculator result: 100",
    }