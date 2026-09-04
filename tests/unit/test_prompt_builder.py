from services.brain.prompt_builder import PromptBuilder
from services.memory.conversation import Message

def test_prompt_builder_creates_basic_prompt():
    messages = [
        Message(
            role="user",
            content="Hello ECHO",
        )
    ]

    prompt = PromptBuilder.build(messages)
    assert "You are ECHO" in prompt
    assert "User: Hello ECHO" in prompt
    assert "ECHO:" in prompt

def test_prompt_builder_includes_system_message():
    messages = [
        Message(
            role="system",
            content="Known facts about the user:\n- name: Sandeep",
        ),
        Message(
            role="user",
            content="What is my name?",
        ),
    ]

    prompt = PromptBuilder.build(messages)
    assert "Known facts about the user:" in prompt
    assert "- name: Sandeep" in prompt
    assert "User: What is my name?" in prompt

def test_prompt_builder_includes_assistant_messages():
    messages = [
        Message(
            role="user",
            content="Hello",
        ),
        Message(
            role="assistant",
            content="Hello! I'm ECHO.",
        ),
        Message(
            role="user",
            content="Who are you?",
        ),
    ]

    prompt = PromptBuilder.build(messages)
    assert "User: Hello" in prompt
    assert "ECHO: Hello! I'm ECHO." in prompt
    assert "User: Who are you?" in prompt

def test_prompt_builder_includes_available_tools():
    messages = [
        Message(
            role="user",
            content="Calculate 10 + 20",
        )
    ]

    tools = [
        {
            "name": "calculator",
            "description": "Performs calculations.",
        }
    ]

    prompt = PromptBuilder.build(
        messages,
        tools=tools,
    )

    assert "Available tools:" in prompt
    assert "- calculator: Performs calculations." in prompt

def test_prompt_builder_includes_tool_result():
    messages = [
        Message(
            role="user",
            content="Calculate 10 + 20",
        )
    ]

    prompt = PromptBuilder.build(
        messages,
        tool_result="30",
    )

    assert "Tool result: 30" in prompt
    assert "Use this result as the factual answer." in prompt
    assert "Do not recalculate or change the tool result." in prompt

def test_prompt_builder_handles_empty_messages():
    prompt = PromptBuilder.build([])

    assert "You are ECHO" in prompt
    assert "Conversation:" in prompt
    assert "ECHO:" in prompt

def test_prompt_builder_handles_empty_tools():
    messages = [
        Message(
            role="user",
            content="Hello",
        )
    ]

    prompt = PromptBuilder.build(
        messages,
        tools=[],
    )

    assert "Available tools:" not in prompt

def test_prompt_builder_preserves_message_order():
    messages = [
        Message(
            role="user",
            content="First message",
        ),
        Message(
            role="assistant",
            content="First response",
        ),
        Message(
            role="user",
            content="Second message",
        ),
    ]

    prompt = PromptBuilder.build(messages)

    first = prompt.index("User: First message")
    response = prompt.index("ECHO: First response")
    second = prompt.index("User: Second message")

    assert first < response < second