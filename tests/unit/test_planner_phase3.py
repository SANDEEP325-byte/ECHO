import json
import pytest

from packages.common.capability_registry import Capability, capability_registry
from packages.interfaces.plan import Plan, PlanStep
from services.brain.planner import Planner, planner


class MockGateway:
    def __init__(self, response: str):
        self.response = response

    async def generate(self, messages, tools=None):
        return self.response


@pytest.mark.anyio
async def test_planner_async_creates_structured_plan_with_arguments():
    capability_registry.register(Capability("calculator", "Performs math"))
    capability_registry.register(Capability("code_runner", "Executes commands"))

    valid_json_response = json.dumps({
        "requires_planning": True,
        "steps": [
            {
                "step_number": 1,
                "description": "Calculate dimensions",
                "tool_name": "calculator",
                "arguments": {"expression": "100 * 20"},
                "purpose": "Find surface area",
            },
            {
                "step_number": 2,
                "description": "Log output to file",
                "tool_name": "code_runner",
                "arguments": {"command": "echo done"},
                "purpose": "Record completion",
            },
        ],
    })

    p = Planner(ai_gateway=MockGateway(valid_json_response))
    plan = await p.create_plan_async("Calculate and record dimensions", requires_planning=True)

    assert plan.requires_planning is True
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "calculator"
    assert plan.steps[0].arguments == {"expression": "100 * 20"}
    assert plan.steps[0].purpose == "Find surface area"
    assert plan.steps[1].tool_name == "code_runner"
    assert plan.steps[1].arguments == {"command": "echo done"}


@pytest.mark.anyio
async def test_planner_async_filters_unregistered_tools():
    capability_registry.register(Capability("calculator", "Performs math"))

    response_with_unregistered = json.dumps({
        "requires_planning": True,
        "steps": [
            {
                "step_number": 1,
                "description": "Calculate expression",
                "tool_name": "calculator",
                "arguments": {"expression": "5 + 5"},
            },
            {
                "step_number": 2,
                "description": "Launch missile",
                "tool_name": "unregistered_dangerous_tool",
                "arguments": {},
            },
        ],
    })

    p = Planner(ai_gateway=MockGateway(response_with_unregistered))
    plan = await p.create_plan_async("Run tasks", requires_planning=True)

    assert plan.requires_planning is True
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "calculator"
    assert plan.steps[1].tool_name is None  # filtered out because not in capability registry


@pytest.mark.anyio
async def test_planner_async_falls_back_on_malformed_json():
    malformed_gateway = MockGateway("Here is your plan: not valid json at all")
    p = Planner(ai_gateway=malformed_gateway)

    plan = await p.create_plan_async("Create a Python project and run it.", requires_planning=True)
    assert plan.requires_planning is True
    assert len(plan.steps) == 4  # Uses heuristic create_plan fallback
