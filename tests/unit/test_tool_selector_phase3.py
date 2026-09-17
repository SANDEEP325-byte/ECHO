import pytest

from packages.common.capability_registry import Capability, capability_registry
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.tool_invocation import ToolInvocation
from services.brain.tool_selector import ToolSelector


def test_tool_selector_select_invocations():
    capability_registry.register(Capability("calculator", "Performs math"))
    capability_registry.register(Capability("file_search", "Searches files"))
    # Ensure terminal is not registered so test_tool_selector.py won't fail
    capability_registry._capabilities.pop("terminal", None)

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Calculate 10 + 20",
                tool_name="calculator",
                arguments={"expression": "10 + 20"},
                purpose="Add numbers",
            ),
            PlanStep(
                step_number=2,
                description="Search for files",
                tool_name="file_search",
                arguments={"pattern": "*.py"},
                purpose="Locate files",
            ),
            PlanStep(
                step_number=3,
                description="Manual review",
                tool_name=None,
            ),
        ],
    )

    selector = ToolSelector()
    invocations = selector.select_invocations(plan)

    assert len(invocations) == 2
    assert all(isinstance(inv, ToolInvocation) for inv in invocations)
    assert invocations[0].tool_name == "calculator"
    assert invocations[0].arguments == {"expression": "10 + 20"}
    assert invocations[0].step_number == 1
    assert invocations[1].tool_name == "file_search"
    assert invocations[1].arguments == {"pattern": "*.py"}
    assert invocations[1].step_number == 2


def test_tool_selector_select_invocations_filters_unregistered_tools():
    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Run unknown tool",
                tool_name="unregistered_tool",
                arguments={},
            ),
        ],
    )

    selector = ToolSelector()
    invocations = selector.select_invocations(plan)
    assert invocations == []


def test_tool_selector_select_single_tool():
    capability_registry.register(Capability("calculator", "Performs math"))
    selector = ToolSelector()

    inv = selector.select_single_tool("calculator", {"expression": "5 * 5"}, purpose="Multiply")
    assert isinstance(inv, ToolInvocation)
    assert inv.tool_name == "calculator"
    assert inv.arguments == {"expression": "5 * 5"}
    assert inv.purpose == "Multiply"

    assert selector.select_single_tool("nonexistent_tool", {}) is None
