"""Canonical E2E integration tests for ECHO Core Pipeline (Phase 9B).

Exercises the real orchestration path:
Request → RequestAnalyzer → ContextBuilder → Reasoning → Planner → ToolSelector → ExecutionEngine → SafetyEngine → ToolRouter → Tool → VerificationEngine → ResponseGenerator → MemoryManager
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request, RequestStatus
from services.brain.brain import ECHOBrain
from services.brain.execution import ExecutionEngine
from services.brain.tool_selector import ToolSelector
from services.security.pending_action_manager import PendingActionManager
from services.security.safety_engine import SafetyEngine
from tests.conftest import FakeAIGateway


@pytest.mark.anyio
async def test_e2e_conversational_greeting_and_identity(fresh_echo_brain: ECHOBrain) -> None:
    """Verify conversational greeting and identity requests complete through ECHOBrain."""
    brain = fresh_echo_brain

    # 1. Greeting
    req_greet = Request(user_input="Hello")
    resp_greet = await brain.process(req_greet)
    assert "ECHO" in resp_greet
    assert "personal AI assistant" in resp_greet
    assert req_greet.status == RequestStatus.ANALYZING

    # 2. Identity
    req_ident = Request(user_input="Who are you?")
    resp_ident = await brain.process(req_ident)
    assert "I'm ECHO" in resp_ident


@pytest.mark.anyio
async def test_e2e_memory_persistence_and_recall_cycle(fresh_echo_brain: ECHOBrain) -> None:
    """Verify MEMORY_SAVE, MEMORY_RECALL, and MEMORY_DELETE across the full request lifecycle."""
    brain = fresh_echo_brain
    memory_mgr = brain.memory_manager
    assert memory_mgr is not None

    # 1. Save user's name
    req_save = Request(user_input="My name is Alex")
    resp_save = await brain.process(req_save)
    assert "Alex" in resp_save
    assert "remember" in resp_save.lower() or "nice to meet you" in resp_save.lower()

    # Fact is stored in memory
    assert memory_mgr.get_fact("name") == "Alex"

    # 2. Recall user's name
    req_recall = Request(user_input="What is my name?")
    resp_recall = await brain.process(req_recall)
    assert "Alex" in resp_recall

    # 3. Delete memory
    req_del = Request(user_input="Forget my name")
    resp_del = await brain.process(req_del)
    assert "forgotten" in resp_del.lower() or "cleared" in resp_del.lower()
    assert memory_mgr.get_fact("name") is None


@pytest.mark.anyio
async def test_e2e_informational_request_via_ai_gateway(fresh_echo_brain: ECHOBrain) -> None:
    """Verify informational queries without tool requirements route through AI Gateway."""
    brain = fresh_echo_brain

    fake_gw = FakeAIGateway(default_response="Python is a versatile programming language.")
    with patch("services.brain.brain.ai_gateway", fake_gw):
        req = Request(user_input="What is Python?")
        resp = await brain.process(req)

        assert "Python is a versatile programming language." in resp
        assert fake_gw.call_count == 1
        # Request context was populated
        assert "recent_messages" in req.context


@pytest.mark.anyio
async def test_e2e_deterministic_tool_execution_calculator(fresh_echo_brain: ECHOBrain) -> None:
    """Verify single-tool deterministic calculation routes and returns formatted output."""
    brain = fresh_echo_brain

    req = Request(user_input="Calculate 45 * 2")
    resp = await brain.process(req)

    assert "90" in resp


@pytest.mark.anyio
async def test_e2e_multi_step_plan_execution_and_verification(fresh_echo_brain: ECHOBrain) -> None:
    """Verify multi-step planning, execution, and verification through the canonical pipeline."""
    brain = fresh_echo_brain

    # Multi-step plan: Step 1 = calculate 10 + 5, Step 2 = calculate 15 * 2
    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Compute initial sum",
                tool_name="calculator",
                arguments={"expression": "10 + 5"},
            ),
            PlanStep(
                step_number=2,
                description="Double the result",
                tool_name="calculator",
                arguments={"expression": "15 * 2"},
            ),
        ],
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(user_input="Compute 10 + 5 then multiply by 2")
        resp = await brain.process(req)

        assert req.status == RequestStatus.COMPLETED
        # Execution succeeded and result is 30
        assert "30" in str(resp)


@pytest.mark.anyio
async def test_security_invariant_no_safety_engine_bypass() -> None:
    """Verify ExecutionEngine mandates SafetyEngine evaluation and cannot execute unconfirmed sensitive tools."""
    pending_mgr = PendingActionManager()
    safety = SafetyEngine()
    engine = ExecutionEngine(
        safety_engine=safety,
        pending_action_manager=pending_mgr,
    )

    req = Request(user_input="Delete critical file")
    # Even if planner emits sensitive operation without confirmation flag
    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Delete system file",
                tool_name="delete_file",
                arguments={"path": "C:\\Windows\\System32\\critical.dll"},
            )
        ],
    )

    res = engine.execute(req, plan)
    # ExecutionEngine must halt, requiring confirmation or blocking
    assert res.requires_confirmation is True or res.success is False
    if res.requires_confirmation:
        assert res.pending_action is not None
        assert res.pending_action["tool"] == "delete_file"


@pytest.mark.anyio
async def test_security_invariant_unregistered_tool_rejected_by_selector() -> None:
    """Verify ToolSelector strictly refuses to select unavailable or unregistered tools."""
    selector = ToolSelector()
    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Run malicious unregistered tool",
                tool_name="unregistered_exploit_tool",
            )
        ],
    )
    req = Request(user_input="Run exploit")
    req = selector.select(req, plan)

    assert "unregistered_exploit_tool" not in req.selected_tools
