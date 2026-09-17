import pytest

from packages.interfaces.execution import ExecutionResult
from services.brain.intent_router import Intent
from services.brain.response_generator import ResponseGenerator


class DummyMemoryManager:
    def __init__(self, facts=None):
        self.facts = facts or {}
        self.deleted = []

    def save_fact(self, key: str, value: str):
        self.facts[key] = value

    def get_fact(self, key: str):
        return self.facts.get(key)

    def get_all_facts(self):
        return dict(self.facts)

    def delete_fact(self, key: str):
        self.deleted.append(key)
        self.facts.pop(key, None)

    def clear_facts(self):
        self.deleted.append("ALL")
        self.facts.clear()


def test_response_generator_fixed_response_greeting():
    gen = ResponseGenerator()
    mem = DummyMemoryManager()
    resp = gen.generate_fixed_response(Intent.GREETING, memory_manager=mem)
    assert resp == "Hello! I'm ECHO, your personal AI assistant. How can I help you today? 😊"

    mem_with_name = DummyMemoryManager({"preferred_name": "Commander"})
    resp_named = gen.generate_fixed_response(Intent.GREETING, memory_manager=mem_with_name)
    assert resp_named == "Hello Commander! I'm ECHO, your personal AI assistant. How can I help you today? 😊"


def test_response_generator_fixed_response_identity():
    gen = ResponseGenerator()
    resp = gen.generate_fixed_response(Intent.IDENTITY)
    assert resp == "I'm ECHO, your personal AI assistant. 😌"

    assert gen.generate_fixed_response(Intent.CALCULATOR) is None


def test_response_generator_memory_save():
    gen = ResponseGenerator()
    mem = DummyMemoryManager()

    resp_name = gen.generate_memory_save_response("My name is Alice.", memory_manager=mem)
    assert "Alice" in resp_name
    assert mem.get_fact("name") == "Alice"

    resp_pref = gen.generate_memory_save_response("Call me Captain", memory_manager=mem)
    assert "Captain" in resp_pref
    assert mem.get_fact("preferred_name") == "Captain"

    resp_color = gen.generate_memory_save_response("My favorite color is purple", memory_manager=mem)
    assert "purple" in resp_color
    assert mem.get_fact("favorite_color") == "purple"


def test_response_generator_memory_recall():
    gen = ResponseGenerator()
    mem = DummyMemoryManager({
        "name": "Alice",
        "preferred_name": "Captain",
        "favorite_color": "purple",
    })

    assert "Alice" in gen.generate_memory_recall_response("what is my name?", memory_manager=mem)
    assert "Captain" in gen.generate_memory_recall_response("what should you call me?", memory_manager=mem)
    assert "purple" in gen.generate_memory_recall_response("what is my favorite color?", memory_manager=mem)

    # All facts summary
    all_summary = gen.generate_memory_recall_response("what do you remember about me?", memory_manager=mem)
    assert "Alice" in all_summary
    assert "Captain" in all_summary
    assert "purple" in all_summary


def test_response_generator_memory_delete():
    gen = ResponseGenerator()
    mem = DummyMemoryManager({
        "name": "Alice",
        "preferred_name": "Captain",
        "favorite_color": "purple",
    })

    resp = gen.generate_memory_delete_response("forget my name", memory_manager=mem)
    assert "forgotten your name" in resp
    assert "name" in mem.deleted

    resp_all = gen.generate_memory_delete_response("forget everything", memory_manager=mem)
    assert "forgotten everything" in resp_all
    assert "ALL" in mem.deleted


def test_response_generator_tool_response():
    gen = ResponseGenerator()
    assert gen.generate_tool_response(Intent.CALCULATOR, "42") == "The result is 42."
    assert gen.generate_tool_response(Intent.TIME, "10:00 AM") == "The current time is 10:00 AM."
    assert gen.generate_tool_response(Intent.DATE, "2026-09-17") == "Today's date is 2026-09-17."
    assert gen.generate_tool_response("custom", "output") == "output"


def test_response_generator_confirmation_prompt():
    gen = ResponseGenerator()
    action = {
        "tool": "delete_file",
        "arguments": {"path": "/important.txt"},
    }
    prompt = gen.generate_confirmation_prompt(action)
    assert "delete_file" in prompt
    assert "/important.txt" in prompt
    assert "(yes/no)" in prompt

    prompt_empty = gen.generate_confirmation_prompt(None)
    assert "requires confirmation" in prompt_empty


def test_response_generator_execution_response():
    gen = ResponseGenerator()

    # Confirmation
    confirm_exec = ExecutionResult(
        success=False,
        requires_confirmation=True,
        pending_action={"tool": "rm", "arguments": {"target": "data"}},
    )
    assert "rm" in gen.generate_execution_response(confirm_exec)

    # Failure
    failed_exec = ExecutionResult(
        success=False,
        error="Disk is full",
    )
    assert gen.generate_execution_response(failed_exec) == "Disk is full"

    # Success
    success_exec = ExecutionResult(
        success=True,
        result="Created project successfully",
    )
    assert gen.generate_execution_response(success_exec) == "Created project successfully"


def test_response_generator_fallback():
    gen = ResponseGenerator()
    fallback = gen.generate_fallback_response("some internal crash")
    assert fallback == "I couldn't process your request because an internal component failed."
    assert "some internal crash" not in fallback
