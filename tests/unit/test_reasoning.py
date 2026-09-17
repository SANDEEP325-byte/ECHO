import pytest

from services.brain.reasoning import (
    ReasoningEngine,
    ReasoningDecision,
    TaskType,
    reasoning_engine,
)


def test_reasoning_decision_structure():
    decision = ReasoningDecision(
        task_type=TaskType.SINGLE_TOOL,
        requires_planning=False,
        tools_needed=["calculator"],
        confidence=0.95,
        deterministic_response=None,
    )
    assert decision.task_type == TaskType.SINGLE_TOOL
    assert decision.requires_planning is False
    assert decision.tools_needed == ["calculator"]
    assert decision.confidence == 0.95


def test_reasoning_fast_path_greeting():
    engine = ReasoningEngine()
    decision = engine.reason("Hello ECHO")
    assert decision.task_type == TaskType.CONVERSATIONAL
    assert decision.requires_planning is False
    assert decision.confidence == 1.0
    assert decision.deterministic_response is not None
    assert "ECHO" in decision.deterministic_response


def test_reasoning_fast_path_identity():
    engine = ReasoningEngine()
    decision = engine.reason("Who are you?")
    assert decision.task_type == TaskType.CONVERSATIONAL
    assert decision.requires_planning is False
    assert decision.confidence == 1.0
    assert decision.deterministic_response == "I'm ECHO, your personal AI assistant. 😌"


def test_reasoning_fast_path_calculator():
    engine = ReasoningEngine()
    decision = engine.reason("Calculate 25 * 4")
    assert decision.task_type == TaskType.SINGLE_TOOL
    assert decision.requires_planning is False
    assert decision.tools_needed == ["calculator"]
    assert decision.confidence == 1.0


def test_reasoning_fast_path_time():
    engine = ReasoningEngine()
    decision = engine.reason("What time is it right now?")
    assert decision.task_type == TaskType.SINGLE_TOOL
    assert decision.requires_planning is False
    assert decision.tools_needed == ["time"]
    assert decision.confidence == 1.0


def test_reasoning_fast_path_date():
    engine = ReasoningEngine()
    decision = engine.reason("What is today's date?")
    assert decision.task_type == TaskType.SINGLE_TOOL
    assert decision.requires_planning is False
    assert decision.tools_needed == ["date"]
    assert decision.confidence == 1.0


def test_reasoning_fast_path_memory_save():
    engine = ReasoningEngine()
    decision = engine.reason("My name is John")
    assert decision.task_type == TaskType.MEMORY
    assert decision.requires_planning is False
    assert decision.confidence == 1.0


def test_reasoning_fast_path_memory_recall():
    engine = ReasoningEngine()
    decision = engine.reason("What is my name?")
    assert decision.task_type == TaskType.MEMORY
    assert decision.requires_planning is False
    assert decision.confidence == 1.0


def test_reasoning_fast_path_memory_delete():
    engine = ReasoningEngine()
    decision = engine.reason("Forget my name")
    assert decision.task_type == TaskType.MEMORY
    assert decision.requires_planning is False
    assert decision.confidence == 1.0


def test_reasoning_complex_multi_step_request():
    engine = ReasoningEngine()
    decision = engine.reason("Create a Python script, then run tests and deploy it.")
    assert decision.task_type == TaskType.MULTI_STEP
    assert decision.requires_planning is True
    assert decision.confidence >= 0.85


def test_reasoning_informational_request():
    engine = ReasoningEngine()
    decision = engine.reason("Explain how neural networks learn.")
    assert decision.task_type == TaskType.INFORMATIONAL
    assert decision.requires_planning is False
    assert decision.tools_needed == []
    assert decision.deterministic_response is None


def test_reasoning_zero_cot_leakage():
    engine = ReasoningEngine()
    decision = engine.reason("How does a compiler work?")
    # Verify no raw chain of thought or internal reasoning tokens exist in the public output
    assert not hasattr(decision, "thought")
    assert not hasattr(decision, "chain_of_thought")
    assert not hasattr(decision, "system_prompt")
