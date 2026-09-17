import pytest

from services.brain.brain import ECHOBrain
from services.brain.intent_router import Intent
from services.memory.facts import fact_memory
from packages.interfaces.execution import ExecutionResult
from packages.interfaces.request import Request, RequestStatus
from services.brain.planner import planner
from packages.interfaces.plan import Plan, PlanStep

class FakeGateway:
    response = "This is a fake response."
    last_messages = None
    last_tools = None

    async def generate(
        self,
        messages,
        tool_result=None,
        tools=None,
    ):
        self.last_messages = messages
        self.last_tools = tools
        return self.response

class FakeToolRouter:
    def __init__(self):
        self.called = False
        self.last_tool = None
        self.last_message = None
        self.execute_tool_result = "100"
        self.last_tool_name = None

    def get_tool_for_intent(self, intent):
        mapping = {
            "calculator": "calculator",
            "time": "time",
            "date": "date",
        }

        return mapping.get(intent)

    def execute_calculator(self, message):
        self.called = True
        self.last_tool = "calculator"
        self.last_message = message
        return 100

    def execute_for_intent(
        self,
        intent,
        message,
    ):
        tool_name = self.get_tool_for_intent(intent)

        if tool_name is None:
            raise ValueError(
                f"No tool mapped to intent: {intent}"
            )

        if tool_name == "calculator":
            return self.execute_tool(
                tool_name,
                message,
            )

        return self.execute_tool(tool_name)

    def execute_tool(
        self,
        tool_name,
        message=None,
        **kwargs,
    ):
        self.called = True
        self.last_tool_name = tool_name
        self.last_message = message

        return self.execute_tool_result

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

class FakeFactMemory:
    def __init__(self, facts=None):
        self.facts = facts or {}

    def save_fact(self, key: str, value: str):
        self.facts[key] = value

    def get_fact(self, key):
        return self.facts.get(key)

    def get_all_facts(self):
        return dict(self.facts)

    def get_context(self):
            if not self.facts:
             return ""

            parts = []

            if "name" in self.facts:
                parts.append(f"User's name is {self.facts['name']}.")

            if "preferred_name" in self.facts:
                parts.append(
                 f"User prefers to be called {self.facts['preferred_name']}."
                )

            if "favorite_color" in self.facts:
                parts.append(
                    f"User's favorite color is {self.facts['favorite_color']}."
                )

            return "Saved user facts:\n" + "\n".join(parts)

    def delete_fact(self, key):
        self.facts.pop(key, None)

    def clear(self):
        self.facts.clear()


@pytest.mark.anyio
async def test_brain_handles_greeting(monkeypatch):
    brain = ECHOBrain()

    fake_gateway = FakeGateway()
    fake_tool_router = FakeToolRouter()
    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

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

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory
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

    assert response == "The result is 100."

    assert fake_memory.messages[-1] == {
        "role": "assistant",
        "content": "The result is 100.",
    }

@pytest.mark.anyio
async def test_save_name_variations():
    brain = ECHOBrain()

    response = await brain.process("I'm Sandeep")

    assert "Sandeep" in response
    assert fact_memory.get_fact("name") == "Sandeep"

@pytest.mark.anyio
async def test_save_name_call_me():
    brain = ECHOBrain()

    response = await brain.process("You can call me Sandeep")

    assert "Sandeep" in response
    assert fact_memory.get_fact("name") == "Sandeep"

@pytest.mark.anyio
async def test_save_favorite_color():
    brain = ECHOBrain()

    response =await brain.process("My favorite color is blue")

    assert "blue" in response.lower()
    assert fact_memory.get_fact("favorite_color") == "blue"

@pytest.mark.anyio
async def test_brain_recalls_name(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process("What is my name?")

    assert response == "Your name is Sandeep. 😌"

@pytest.mark.anyio
async def test_brain_recalls_preferred_name(monkeypatch):
    brain =ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process("What should you call me?")

    assert response == "I'll call you Boss. 😉"

@pytest.mark.anyio
async def test_brain_recalls_favorite_color(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "favorite_color" : "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process("What is my favorite color?")
    assert response == "Your favorite color is blue. 🫟"

@pytest.mark.anyio
async def test_brain_recalls_all_user_facts(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "Tell me what you remember about me."
    )

    assert "Sandeep" in response
    assert "Boss" in response
    assert "blue" in response


@pytest.mark.anyio
async def test_brain_forgets_favorite_color(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name" : "Sandeep",
            "preferred_name": "Boss",
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "Forget my favorite color"
    )

    assert response == "Okay, I've forgotten your favorite color."
    assert fake_fact_memory.get_fact("favorite_color") is None
    assert fake_fact_memory.get_fact("name") == "Sandeep"
    assert fake_fact_memory.get_fact("preferred_name") == "Boss"

@pytest.mark.anyio
async def test_brain_forgets_name(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "Forget my name"
    )

    assert response == "Okay, I've forgotten your name."
    assert fake_fact_memory.get_fact("name") is None
    assert fake_fact_memory.get_fact("preferred_name") == "Boss"
    assert fake_fact_memory.get_fact("favorite_color") == "blue"

@pytest.mark.anyio
async def test_brain_recalls_dynamic_user_facts(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "Tell me what you remember about me."
    )

    assert "Sandeep" in response
    assert "Boss" in response
    assert "blue" in response
    assert "your name is Sandeep" in response
    assert "you prefer to be called Boss" in response
    assert "your favorite color is blue" in response

@pytest.mark.anyio
async def test_name_and_preferred_name_are_stored_separately(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
            "services.brain.brain.fact_memory",
            fake_fact_memory,
    )

    await brain.process("My name is Sandeep")
    await brain.process("Call me Boss")

    assert fake_fact_memory.get_fact("name") == "Sandeep"
    assert fake_fact_memory.get_fact("preferred_name") == "Boss"

@pytest.mark.anyio
async def test_updating_preferred_name_does_not_change_real_name(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process("My name is Sandeep")
    await brain.process("Call me Boss")
    await brain.process("Actually, call me Captain")

    assert fake_fact_memory.get_fact("name") == "Sandeep"
    assert fake_fact_memory.get_fact("preferred_name") == "Captain"

@pytest.mark.anyio
async def test_greeting_uses_preferred_name(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process("Hello ECHO")

    assert response.startswith("Hello Boss!")
    assert "Sandeep" not in response

@pytest.mark.anyio
async def test_brain_updates_name(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process("Actually, my name is Rahul")

    assert fake_fact_memory.get_fact("name") == "Rahul"
    assert "Rahul" in response


@pytest.mark.anyio
async def test_brain_updates_preferred_name(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process("Actually, call me Captain")

    assert fake_fact_memory.get_fact("preferred_name") == "Captain"
    assert "Captain" in response


@pytest.mark.anyio
async def test_brain_updates_favorite_color(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "Actually, my favorite color is green"
    )

    assert fake_fact_memory.get_fact("favorite_color") == "green"
    assert "green" in response.lower()

@pytest.mark.anyio
async def test_brain_handles_natural_name_correction(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process("No, my name is Rahul")

    assert fake_fact_memory.get_fact("name") == "Rahul"
    assert "Rahul" in response


@pytest.mark.anyio
async def test_brain_handles_natural_preferred_name_correction(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "I actually prefer to be called Captain"
    )

    assert fake_fact_memory.get_fact("preferred_name") == "Captain"
    assert "Captain" in response


@pytest.mark.anyio
async def test_brain_handles_from_now_on_preferred_name(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process("From now on, call me Captain")

    assert fake_fact_memory.get_fact("preferred_name") == "Captain"
    assert "Captain" in response


@pytest.mark.anyio
async def test_brain_handles_natural_color_correction(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "My favorite color is actually green"
    )

    assert fake_fact_memory.get_fact("favorite_color") == "green"
    assert "green" in response.lower()

@pytest.mark.anyio
async def test_brain_normalizes_name_update(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "Actually, my name is Rahul."
    )

    assert fake_fact_memory.get_fact("name") == "Rahul"
    assert "Rahul" in response


@pytest.mark.anyio
async def test_brain_normalizes_preferred_name_update(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "From now on, call me Captain."
    )

    assert fake_fact_memory.get_fact("preferred_name") == "Captain"
    assert "Captain" in response


@pytest.mark.anyio
async def test_brain_normalizes_favorite_color_update(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "My favorite color is actually green."
    )

    assert fake_fact_memory.get_fact("favorite_color") == "green"
    assert "green" in response.lower()

@pytest.mark.anyio
async def test_brain_keeps_name_when_preferred_name_changes(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process("Call me Captain")

    assert fake_fact_memory.get_fact("name") == "Sandeep"
    assert fake_fact_memory.get_fact("preferred_name") == "Captain"


@pytest.mark.anyio
async def test_brain_keeps_preferred_name_when_name_changes(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process("My name is Rahul")

    assert fake_fact_memory.get_fact("name") == "Rahul"
    assert fake_fact_memory.get_fact("preferred_name") == "Boss"


@pytest.mark.anyio
async def test_brain_keeps_favorite_color_when_name_changes(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process("My name is Rahul")

    assert fake_fact_memory.get_fact("name") == "Rahul"
    assert fake_fact_memory.get_fact("favorite_color") == "blue"


@pytest.mark.anyio
async def test_brain_keeps_name_when_favorite_color_changes(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "favorite_color": "blue",
        }
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process(
        "My favorite color is actually green"
    )

    assert fake_fact_memory.get_fact("name") == "Sandeep"
    assert fake_fact_memory.get_fact("favorite_color") == "green"

@pytest.mark.anyio
async def test_brain_uses_preferred_name_in_general_conversation(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
        }
    )

    fake_gateway = FakeGateway()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway",
        fake_gateway,
    )

    response = await brain.process(
        "Tell me something interesting."
    )

    assert response == fake_gateway.response
    assert fake_gateway.last_messages is not None

    system_messages = [
        message
        for message in fake_gateway.last_messages
        if message.role == "system"
    ]

    assert system_messages
    assert "Sandeep" in system_messages[0].content
    assert "Boss" in system_messages[0].content


@pytest.mark.anyio
async def test_brain_includes_all_saved_facts_in_general_conversation(monkeypatch,):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        {
            "name": "Sandeep",
            "preferred_name": "Boss",
            "favorite_color": "blue",
        }
    )

    fake_gateway = FakeGateway()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway",
        fake_gateway,
    )

    response = await brain.process(
        "Tell me something interesting."
    )

    assert response == fake_gateway.response

    system_messages = [
        message
        for message in fake_gateway.last_messages
        if message.role == "system"
    ]

    assert system_messages

    context = system_messages[0].content

    assert "Sandeep" in context
    assert "Boss" in context
    assert "blue" in context

@pytest.mark.anyio
async def test_brain_uses_time_tool(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()
    fake_tool_router = FakeToolRouter()

    fake_tool_router.execute_tool_result = "11:30:45 PM"

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.tool_router",
        fake_tool_router,
    )

    response = await brain.process(
        "What time is it?"
    )

    assert response == "The current time is 11:30:45 PM."
    assert fake_tool_router.last_tool_name == "time"

@pytest.mark.anyio
async def test_brain_passes_available_tools_to_gateway(monkeypatch):
    brain = ECHOBrain()

    fake_gateway = FakeGateway()
    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway",
        fake_gateway,
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "Tell me something interesting."
    )

    assert response == fake_gateway.response
    assert fake_gateway.last_tools is not None
    assert isinstance(fake_gateway.last_tools, list)

@pytest.mark.anyio
async def test_brain_passes_registered_tool_definitions(monkeypatch,):
    brain = ECHOBrain()

    fake_gateway = FakeGateway()
    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway",
        fake_gateway,
    )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process(
        "Tell me something interesting."
    )

    tool_names = [
        tool["name"]
        for tool in fake_gateway.last_tools
    ]

    assert "calculator" in tool_names
    assert "time" in tool_names
    assert "date" in tool_names

@pytest.mark.anyio
async def test_brain_executes_tool_for_intent(monkeypatch):
    brain = ECHOBrain()

    fake_tool_router = FakeToolRouter()

    fake_tool_router.execute_tool_result = "11:30:45 PM"

    monkeypatch.setattr(
        "services.brain.brain.tool_router",
        fake_tool_router,
    )

    result = brain._execute_tool_for_intent(
        Intent.TIME,
        "What time is it?",
    )

    assert result == "11:30:45 PM"
    assert fake_tool_router.called is True
    assert fake_tool_router.last_tool_name == "time"

@pytest.mark.anyio
async def test_brain_calls_verification_after_execution(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()
    fake_gateway = FakeGateway()

    class FakeExecutionEngine:
        called = False

        def execute(self, request, plan):
            self.called = True
            return ExecutionResult(
                success=True,
                result="Execution completed.",
            )

    class FakeVerificationEngine:
        called = False

        def verify(self, request, plan):
            self.called = True
            return ExecutionResult(
                success=True,
                result="Verification completed.",
            )

    fake_execution = FakeExecutionEngine()
    fake_verification = FakeVerificationEngine()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway",
        fake_gateway,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        fake_execution,
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        fake_verification,
    )

    await brain.process(
        "Create and run a Python application."
    )

    assert fake_execution.called is True
    assert fake_verification.called is True

@pytest.mark.anyio
async def test_brain_does_not_verify_failed_execution(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    class FakeExecutionEngine:
        called = False

        def execute(self, request, plan):
            self.called = True
            return ExecutionResult(
                success=False,
                error="Tool execution failed.",
            )

    class FakeVerificationEngine:
        called = False

        def verify(self, request, plan):
            self.called = True
            return ExecutionResult(
                success=True,
                result="Verification completed.",
            )

    fake_execution = FakeExecutionEngine()
    fake_verification = FakeVerificationEngine()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        fake_execution,
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        fake_verification,
    )

    await brain.process(
        "Create and run a Python application."
    )

    assert fake_execution.called is True
    assert fake_verification.called is False

@pytest.mark.anyio
async def test_brain_handles_verification_failure(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    class FakeExecutionEngine:
        def execute(self, request, plan):
            return ExecutionResult(
                success=True,
                result="Execution completed.",
            )

    class FakeVerificationEngine:
        def verify(self, request, plan):
            return ExecutionResult(
                success=False,
                error="Verification failed.",
            )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        FakeVerificationEngine(),
    )

    response = await brain.process(
        "Create and run a Python application."
    )

    assert response == "Verification failed."

@pytest.mark.anyio
async def test_brain_returns_verified_execution_result(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    class FakeExecutionEngine:
        def execute(self, request, plan):
            return ExecutionResult(
                success=True,
                result="Application created and executed.",
            )

    class FakeVerificationEngine:
        def verify(self, request, execution_result):
            return ExecutionResult(
                success=True,
                result="Execution verified successfully.",
            )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        FakeVerificationEngine(),
    )

    response = await brain.process(
        "Create and run a Python application."
    )

    assert response == "Application created and executed."

@pytest.mark.anyio
async def test_brain_skips_execution_and_verification_for_simple_request(
    monkeypatch,
):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    class FakeExecutionEngine:
        called = False

        def execute(self, request, plan):
            self.called = True
            return ExecutionResult(
                success=True,
                result="Should not execute.",
            )

    class FakeVerificationEngine:
        called = False

        def verify(self, request, execution_result):
            self.called = True
            return ExecutionResult(
                success=True,
                result="Should not verify.",
            )

    fake_execution = FakeExecutionEngine()
    fake_verification = FakeVerificationEngine()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        fake_execution,
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        fake_verification,
    )

    response = await brain.process(
        "What is Python?"
    )

    assert fake_execution.called is False
    assert fake_verification.called is False
    assert response

@pytest.mark.anyio
async def test_brain_marks_request_completed_after_successful_verification(
    monkeypatch,
):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    captured_request = None

    class FakeExecutionEngine:
        def execute(self, request, plan):
            nonlocal captured_request
            captured_request = request

            return ExecutionResult(
                success=True,
                result="Application created and executed.",
            )

    class FakeVerificationEngine:
        def verify(self, request, execution_result):
            return ExecutionResult(
                success=True,
                result="Verification completed.",
            )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        FakeVerificationEngine(),
    )

    await brain.process(
        "Create and run a Python application."
    )

    assert captured_request is not None
    assert captured_request.status == RequestStatus.COMPLETED

@pytest.mark.anyio
async def test_brain_marks_request_failed_when_execution_fails(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    captured_request = None

    class FakeExecutionEngine:
        def execute(self, request, plan):
            nonlocal captured_request
            captured_request = request

            return ExecutionResult(
                success=False,
                error="Execution failed.",
            )

    class FakeVerificationEngine:
        called = False

        def verify(self, request, execution_result):
            self.called = True

            return ExecutionResult(
                success=True,
                result="Should not verify.",
            )

    fake_verification = FakeVerificationEngine()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        fake_verification,
    )

    response = await brain.process(
        "Create and run a Python application."
    )

    assert captured_request is not None
    assert captured_request.status == RequestStatus.FAILED
    assert captured_request.error == "Execution failed."
    assert fake_verification.called is False
    assert response == "Execution failed."

@pytest.mark.anyio
async def test_brain_marks_request_failed_when_verification_fails(
    monkeypatch,
):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    captured_request = None

    class FakeExecutionEngine:
        def execute(self, request, plan):
            nonlocal captured_request
            captured_request = request

            return ExecutionResult(
                success=True,
                result="Application created and executed.",
            )

    class FakeVerificationEngine:
        def verify(self, request, execution_result):
            return ExecutionResult(
                success=False,
                error="Verification failed.",
            )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        FakeVerificationEngine(),
    )

    response = await brain.process(
        "Create and run a Python application."
    )

    assert captured_request is not None
    assert captured_request.status == RequestStatus.FAILED
    assert captured_request.error == "Verification failed."
    assert response == "Verification failed."

@pytest.mark.anyio
async def test_brain_does_not_return_execution_result_when_verification_fails(
    monkeypatch,
):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    class FakeExecutionEngine:
        def execute(self, request, plan):
            return ExecutionResult(
                success=True,
                result="UNVERIFIED EXECUTION RESULT",
            )

    class FakeVerificationEngine:
        def verify(self, request, execution_result):
            return ExecutionResult(
                success=False,
                error="Verification failed.",
            )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        FakeVerificationEngine(),
    )

    response = await brain.process(
        "Create and run a Python application."
    )

    assert response == "Verification failed."
    assert response != "UNVERIFIED EXECUTION RESULT"

@pytest.mark.anyio
async def test_brain_passes_execution_result_to_verification(
    monkeypatch,
):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    captured_execution_result = None

    class FakeExecutionEngine:
        def execute(self, request, plan):
            return ExecutionResult(
                success=True,
                result="Application created.",
            )

    class FakeVerificationEngine:
        def verify(self, request, execution_result):
            nonlocal captured_execution_result
            captured_execution_result = execution_result

            return ExecutionResult(
                success=True,
                result="Verified.",
            )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        FakeVerificationEngine(),
    )

    response = await brain.process(
        "Create and run a Python application."
    )

    assert captured_execution_result is not None
    assert isinstance(captured_execution_result, ExecutionResult)
    assert captured_execution_result.success is True
    assert captured_execution_result.result == "Application created."
    assert response == "Application created."

@pytest.mark.anyio
async def test_brain_does_not_execute_or_verify_direct_request(
    monkeypatch,
):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    class FakeExecutionEngine:
        called = False

        def execute(self, request, plan):
            self.called = True
            return ExecutionResult(
                success=True,
                result="Should not execute.",
            )

    class FakeVerificationEngine:
        called = False

        def verify(self, request, execution_result):
            self.called = True
            return ExecutionResult(
                success=True,
                result="Should not verify.",
            )

    fake_execution = FakeExecutionEngine()
    fake_verification = FakeVerificationEngine()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        fake_execution,
    )

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        fake_verification,
    )

    response = await brain.process(
        "Hello"
    )

    assert fake_execution.called is False
    assert fake_verification.called is False
    assert response

@pytest.mark.anyio
async def test_brain_preserves_status_for_direct_request():
    brain = ECHOBrain()

    request = Request(
        user_input="Hello",
    )

    plan = planner.create_plan(
        request.user_input,
        requires_planning=False,
    )

    assert plan.requires_planning is False
    assert request.status != RequestStatus.PLANNING
    assert request.status != RequestStatus.EXECUTING
    assert request.status != RequestStatus.VERIFYING

@pytest.mark.anyio
async def test_brain_direct_request_does_not_enter_execution_lifecycle(
    monkeypatch,
):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    captured_request = None

    class FakeRequestAnalyzer:
        def analyze(self, request):
            return request

    class FakeContextBuilder:
        def build(self, request, memory, facts):
            request.context = {
                "recent_messages": [],
                "facts": {},
            }
            return request

    class FakePlanner:
        def create_plan(self, user_input, requires_planning):
            return Plan(
                requires_planning=False,
                steps=[],
            )

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.planner",
        FakePlanner(),
    )

    class FakeToolSelector:
        def select(self, request, plan):
            nonlocal captured_request
            captured_request = request
            return request

    monkeypatch.setattr(
        "services.brain.brain.tool_selector",
        FakeToolSelector(),
    )

    response = await brain.process("Hello")

    assert response
    assert captured_request is not None
    assert captured_request.status not in (
        RequestStatus.PLANNING,
        RequestStatus.EXECUTING,
        RequestStatus.VERIFYING,
    )

@pytest.mark.anyio
async def test_brain_handles_request_analyzer_failure(monkeypatch):
    brain = ECHOBrain()

    class FakeRequestAnalyzer:
        def analyze(self, request):
            raise RuntimeError("Request analysis failed.")

    monkeypatch.setattr(
        "services.brain.brain.request_analyzer",
        FakeRequestAnalyzer(),
    )

    response = await brain.process("Hello")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )

@pytest.mark.anyio
async def test_brain_does_not_call_context_builder_when_request_analyzer_fails(
    monkeypatch,
):
    brain = ECHOBrain()

    context_builder_called = False

    class FakeRequestAnalyzer:
        def analyze(self, request):
            raise RuntimeError("Request analysis failed.")

    class FakeContextBuilder:
        def build(self, request, memory, facts):
            nonlocal context_builder_called
            context_builder_called = True
            return request

    monkeypatch.setattr(
        "services.brain.brain.request_analyzer",
        FakeRequestAnalyzer(),
    )

    monkeypatch.setattr(
        "services.brain.brain.context_builder",
        FakeContextBuilder(),
    )

    response = await brain.process("Hello")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )
    assert context_builder_called is False

@pytest.mark.anyio
async def test_brain_handles_context_builder_failure(monkeypatch):
    brain = ECHOBrain()

    class FakeContextBuilder:
        def build(self, request, memory, facts):
            raise RuntimeError("Context building failed.")

    monkeypatch.setattr(
        "services.brain.brain.context_builder",
        FakeContextBuilder(),
    )

    response = await brain.process("Hello")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )

@pytest.mark.anyio
async def test_brain_does_not_call_planner_when_context_builder_fails(
    monkeypatch,
):
    brain = ECHOBrain()

    planner_called = False

    class FakeContextBuilder:
        def build(self, request, memory, facts):
            raise RuntimeError("Context building failed.")

    class FakePlanner:
        def create_plan(self, user_input, requires_planning):
            nonlocal planner_called
            planner_called = True
            return Plan(
                requires_planning=False,
                steps=[],
            )

    monkeypatch.setattr(
        "services.brain.brain.context_builder",
        FakeContextBuilder(),
    )

    monkeypatch.setattr(
        "services.brain.brain.planner",
        FakePlanner(),
    )

    response = await brain.process("Hello")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )
    assert planner_called is False

@pytest.mark.anyio
async def test_brain_handles_planner_failure(monkeypatch):
    brain = ECHOBrain()

    class FakePlanner:
        def create_plan(self, user_input, requires_planning):
            raise RuntimeError("Planning failed.")

    monkeypatch.setattr(
        "services.brain.brain.planner",
        FakePlanner(),
    )

    response = await brain.process("Hello")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )

@pytest.mark.anyio
async def test_brain_does_not_call_tool_selector_when_planner_fails(
    monkeypatch,
):
    brain = ECHOBrain()

    tool_selector_called = False

    class FakePlanner:
        def create_plan(self, user_input, requires_planning):
            raise RuntimeError("Planning failed.")

    class FakeToolSelector:
        def select(self, request, plan):
            nonlocal tool_selector_called
            tool_selector_called = True
            return request

    monkeypatch.setattr(
        "services.brain.brain.planner",
        FakePlanner(),
    )

    monkeypatch.setattr(
        "services.brain.brain.tool_selector",
        FakeToolSelector(),
    )

    response = await brain.process("Hello")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )
    assert tool_selector_called is False

@pytest.mark.anyio
async def test_brain_handles_tool_selector_failure(monkeypatch):
    brain = ECHOBrain()

    class FakeToolSelector:
        def select(self, request, plan):
            raise RuntimeError("Tool selection failed.")

    monkeypatch.setattr(
        "services.brain.brain.tool_selector",
        FakeToolSelector(),
    )

    response = await brain.process("Hello")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )

@pytest.mark.anyio
async def test_brain_does_not_call_execution_when_tool_selector_fails(
    monkeypatch,
):
    brain = ECHOBrain()

    execution_called = False

    class FakeToolSelector:
        def select(self, request, plan):
            raise RuntimeError("Tool selection failed.")

    class FakeExecutionEngine:
        def execute(self, request, plan):
            nonlocal execution_called
            execution_called = True
            return ExecutionResult(
                success=True,
                result="Should not execute.",
            )

    monkeypatch.setattr(
        "services.brain.brain.tool_selector",
        FakeToolSelector(),
    )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    response = await brain.process("Hello")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )
    assert execution_called is False

@pytest.mark.anyio
async def test_brain_handles_execution_exception(monkeypatch):
    brain = ECHOBrain()

    class FakeExecutionEngine:
        def execute(self, request, plan):
            raise RuntimeError("Execution engine crashed.")

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    # Force the request through the planning/execution path.
    class FakePlanner:
        def create_plan(self, user_input, requires_planning):
            return Plan(
                requires_planning=True,
                steps=[
                    PlanStep(
                        step_number=1,
                        description="Execute task.",
                    ),
                ],
            )

    monkeypatch.setattr(
        "services.brain.brain.planner",
        FakePlanner(),
    )

    response = await brain.process("Create something")

    assert response == "I couldn't process your request because an internal component failed."

@pytest.mark.anyio
async def test_brain_saves_favorite_color_to_memory(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "My favorite color is black."
    )

    assert fake_fact_memory.get_fact("favorite_color") == "black"
    assert "black" in response.lower()

@pytest.mark.anyio
async def test_brain_can_recall_saved_favorite_color(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process(
        "My favorite color is black."
    )

    response = await brain.process(
        "What is my favorite color?"
    )

    assert fake_fact_memory.get_fact("favorite_color") == "black"
    assert "black" in response.lower()

@pytest.mark.anyio
async def test_brain_can_delete_saved_favorite_color(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process(
        "My favorite color is black."
    )

    assert fake_fact_memory.get_fact("favorite_color") == "black"

    await brain.process(
        "Forget my favorite color."
    )

    assert fake_fact_memory.get_fact("favorite_color") is None

    response = await brain.process(
        "What is my favorite color?"
    )

    assert "don't know" in response.lower()

@pytest.mark.anyio
async def test_brain_can_forget_all_memories(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process(
        "My name is Sandeep."
    )

    await brain.process(
        "My favorite color is black."
    )

    assert fake_fact_memory.get_fact("name") == "Sandeep"
    assert fake_fact_memory.get_fact("favorite_color") == "black"

    await brain.process(
        "Forget everything."
    )

    assert fake_fact_memory.get_fact("name") is None
    assert fake_fact_memory.get_fact("favorite_color") is None
    assert fake_fact_memory.get_all_facts() == {}

    response = await brain.process(
        "What do you remember about me?"
    )

    assert "don't have any saved information" in response.lower()

@pytest.mark.anyio
async def test_brain_persists_user_and_assistant_messages(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    response = await brain.process(
        "Hello"
    )

    assert len(fake_memory.messages) == 2

    assert fake_memory.messages[0]["role"] == "user"
    assert fake_memory.messages[0]["content"] == "Hello"

    assert fake_memory.messages[1]["role"] == "assistant"
    assert fake_memory.messages[1]["content"] == response

@pytest.mark.anyio
async def test_brain_uses_previous_conversation_context(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    await brain.process(
        "Hello"
    )

    await brain.process(
        "How are you?"
    )

    assert len(fake_memory.messages) == 4

    assert fake_memory.messages[0]["role"] == "user"
    assert fake_memory.messages[0]["content"] == "Hello"

    assert fake_memory.messages[1]["role"] == "assistant"

    assert fake_memory.messages[2]["role"] == "user"
    assert fake_memory.messages[2]["content"] == "How are you?"

    assert fake_memory.messages[3]["role"] == "assistant"

@pytest.mark.anyio
async def test_brain_injects_previous_messages_into_llm_context(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    captured_messages = None

    async def fake_generate(messages, tools=None):
        nonlocal captured_messages
        captured_messages = messages

        return "I'm doing well!"

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway.generate",
        fake_generate,
    )

    await brain.process("Tell me something.")

    await brain.process("How are you?")

    assert captured_messages is not None

    contents = [
        message.content
        for message in captured_messages
    ]

    assert "Tell me something." in contents
    assert "How are you?" in contents

@pytest.mark.anyio
async def test_brain_injects_saved_facts_into_llm_context(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory(
        facts={
            "name": "Sandeep",
        }
    )

    captured_messages = None

    async def fake_generate(messages, tools=None):
        nonlocal captured_messages
        captured_messages = messages

        return "Hello Sandeep!"

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway.generate",
        fake_generate,
    )

    await brain.process("Tell me something interesting about Python.")

    assert captured_messages is not None

    system_messages = [
        message.content
        for message in captured_messages
        if message.role == "system"
    ]

    assert len(system_messages) == 1
    assert "Known facts about the user:" in system_messages[0]
    assert "name: Sandeep" in system_messages[0]

@pytest.mark.anyio
async def test_brain_handles_empty_fact_context(monkeypatch):
    brain = ECHOBrain()

    fake_memory = FakeMemory()
    fake_fact_memory = FakeFactMemory()

    captured_messages = None

    async def fake_generate(messages, tools=None):
        nonlocal captured_messages
        captured_messages = messages

        return "Python is a programming language."

    monkeypatch.setattr(
        "services.brain.brain.persistent_memory",
        fake_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.fact_memory",
        fake_fact_memory,
    )

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway.generate",
        fake_generate,
    )

    response = await brain.process(
        "Tell me something about Python."
    )

    assert response == "Python is a programming language."
    assert captured_messages is not None

    system_messages = [
        message
        for message in captured_messages
        if message.role == "system"
    ]

    assert system_messages == []

@pytest.mark.anyio
async def test_brain_handles_verification_exception(monkeypatch):
    brain = ECHOBrain()

    class FakeExecutionEngine:
        def execute(self, request, plan):
            return ExecutionResult(
                success=True,
                result="Execution completed.",
            )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    class FakeVerificationEngine:
        def verify(self, request, execution_result):
            raise RuntimeError("Verification engine crashed.")

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        FakeVerificationEngine(),
    )

    class FakePlanner:
        def create_plan(self, user_input, requires_planning):
            return Plan(
                requires_planning=True,
                steps=[
                    PlanStep(
                        step_number=1,
                        description="Execute task.",
                    ),
                ],
            )

    monkeypatch.setattr(
        "services.brain.brain.planner",
        FakePlanner(),
    )

    response = await brain.process("Create something")

    assert response == "I couldn't process your request because an internal component failed."

@pytest.mark.anyio
async def test_brain_does_not_complete_when_verification_raises(monkeypatch):
    brain = ECHOBrain()

    class FakePlanner:
        def create_plan(self, user_input, requires_planning):
            return Plan(
                requires_planning=True,
                steps=[
                    PlanStep(
                        step_number=1,
                        description="Execute task.",
                    ),
                ],
            )

    monkeypatch.setattr(
        "services.brain.brain.planner",
        FakePlanner(),
    )

    class FakeExecutionEngine:
        def execute(self, request, plan):
            return ExecutionResult(
                success=True,
                result="Execution completed.",
            )

    monkeypatch.setattr(
        "services.brain.brain.execution_engine",
        FakeExecutionEngine(),
    )

    class FakeVerificationEngine:
        def verify(self, request, execution_result):
            raise RuntimeError("Verification engine crashed.")

    monkeypatch.setattr(
        "services.brain.brain.verification_engine",
        FakeVerificationEngine(),
    )

    response = await brain.process("Create something")

    assert response == (
        "I couldn't process your request because an internal component failed."
    )

@pytest.mark.anyio
async def test_brain_handles_ai_gateway_exception(monkeypatch):
    brain = ECHOBrain()

    async def fake_generate(messages, tools=None):
        raise RuntimeError("AI Gateway crashed.")

    monkeypatch.setattr(
        "services.brain.brain.ai_gateway.generate",
        fake_generate,
    )

    result = await brain.process("Tell me something interesting.")

    assert result == "I couldn't process your request because an internal component failed."

def test_brain_save_memory_uses_memory_manager():
    class FakeMemoryManager:
        def __init__(self):
            self.saved = []

        def save_fact(self, key, value):
            self.saved.append((key, value))

    fake_memory_manager = FakeMemoryManager()

    result = ECHOBrain._save_memory(
        "my name is Sandeep",
        memory_manager=fake_memory_manager,
    )

    assert result is not None
    assert fake_memory_manager.saved == [
        ("name", "Sandeep")
    ]
    
def test_brain_recall_memory_uses_memory_manager():
    class FakeMemoryManager:
        def get_fact(self, key):
            assert key == "name"
            return "Sandeep"

        def get_all_facts(self):
            return {}

    fake_memory_manager = FakeMemoryManager()

    result = ECHOBrain._recall_memory(
        "What is my name?",
        memory_manager=fake_memory_manager,
    )

    assert result == "Your name is Sandeep. 😌"
    
def test_brain_delete_memory_uses_memory_manager():
    class FakeMemoryManager:
        def __init__(self):
            self.deleted = []

        def delete_fact(self, key):
            self.deleted.append(key)

        def clear_facts(self):
            self.deleted.append("ALL")

    fake_memory_manager = FakeMemoryManager()

    result = ECHOBrain._delete_memory(
        "forget my name",
        memory_manager=fake_memory_manager,
    )

    assert result == "Okay, I've forgotten your name."
    assert fake_memory_manager.deleted == ["name"]
    
def test_brain_fixed_response_uses_memory_manager():
    class FakeMemoryManager:
        def get_fact(self, key):
            assert key == "preferred_name"
            return "Boss"

    fake_memory_manager = FakeMemoryManager()

    result = ECHOBrain._fixed_response(
        Intent.GREETING,
        memory_manager=fake_memory_manager,
    )

    assert result == (
        "Hello Boss! I'm ECHO, "
        "your personal AI assistant. How can I help you today? 😊"
    )
    
def test_brain_memory_manager_accepts_messages():
    class FakeMemoryManager:
        def __init__(self):
            self.saved_messages = []

        def save_message(self, role, content):
            self.saved_messages.append((role, content))

    fake_memory_manager = FakeMemoryManager()
    brain = ECHOBrain(memory_manager=fake_memory_manager)

    # Verify the manager itself accepts both message types.
    brain.memory_manager.save_message(
        role="user",
        content="Hello ECHO",
    )
    brain.memory_manager.save_message(
        role="assistant",
        content="Hello! How can I help?",
    )

    assert fake_memory_manager.saved_messages == [
        ("user", "Hello ECHO"),
        ("assistant", "Hello! How can I help?"),
    ]
    
@pytest.mark.anyio
async def test_brain_persists_messages_using_memory_manager(monkeypatch):
    class FakeMemoryManager:
        def __init__(self):
            self.messages = []

        def get_recent_messages(self, limit=20):
            return []

        def get_all_facts(self):
            return {}

        def get_fact(self, key):
            return None

        def save_message(self, role, content):
            self.messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

    fake_memory_manager = FakeMemoryManager()
    brain = ECHOBrain(memory_manager=fake_memory_manager)

    response = await brain.process("Hello")

    assert len(fake_memory_manager.messages) == 2

    assert fake_memory_manager.messages[0]["role"] == "user"
    assert fake_memory_manager.messages[0]["content"] == "Hello"

    assert fake_memory_manager.messages[1]["role"] == "assistant"
    assert fake_memory_manager.messages[1]["content"] == response


@pytest.mark.anyio
async def test_brain_injects_semantic_memory_into_prompt(monkeypatch):
    import services.brain.brain as brain_module

    class FakeGateway:
        def __init__(self):
            self.last_messages = None

        async def generate(self, messages, tools=None):
            self.last_messages = messages
            return "Response using memory context."

    class FakeMemoryManager:
        def __init__(self):
            self.messages = []

        def get_recent_messages(self, limit=20):
            return []

        def get_all_facts(self):
            return {}

        def get_fact(self, key):
            return None

        def search_semantic_memory(self, query, limit=5, **kwargs):
            return [
                {
                    "id": "mem-arch",
                    "content": "ECHO uses a 4-layer modular memory architecture.",
                }
            ]

        def save_message(self, role, content):
            self.messages.append({"role": role, "content": content})

    fake_gateway = FakeGateway()
    monkeypatch.setattr(brain_module, "ai_gateway", fake_gateway)

    fake_memory_manager = FakeMemoryManager()
    brain = ECHOBrain(memory_manager=fake_memory_manager)

    response = await brain.process("Tell me about ECHO's architecture.")

    assert response == "Response using memory context."
    assert fake_gateway.last_messages is not None
    system_contents = [m.content for m in fake_gateway.last_messages if m.role == "system"]
    assert any(
        "Relevant context from memory:" in c
        and "ECHO uses a 4-layer modular memory architecture." in c
        for c in system_contents
    )