import pytest

from services.brain.brain import ECHOBrain
from services.brain.intent_router import Intent
from services.memory.facts import fact_memory

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