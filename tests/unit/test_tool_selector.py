from packages.common.capability_registry import ( Capability, capability_registry, )
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request
from services.brain.tool_selector import ToolSelector

def test_tool_selector_selects_available_tool():
    capability_registry.register(
        Capability(
            name="calculator",
            description="Performs calculations.",
        )
    )

    request = Request(
        user_input="Calculate 10 + 20"
    )

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Calculate the expression.",
                tool_name="calculator",
            )
        ],
    )

    result = ToolSelector().select(request, plan)

    assert result.selected_tools == ["calculator"]


def test_tool_selector_ignores_unavailable_tool():
    request = Request(
        user_input="Create a project"
    )

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Create the project.",
                tool_name="terminal",
            )
        ],
    )

    result = ToolSelector().select(request, plan)

    assert result.selected_tools == []


def test_tool_selector_does_not_duplicate_tools():
    capability_registry.register(
        Capability(
            name="calculator",
            description="Performs calculations.",
        )
    )

    request = Request(
        user_input="Calculate multiple things"
    )

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="First calculation.",
                tool_name="calculator",
            ),
            PlanStep(
                step_number=2,
                description="Second calculation.",
                tool_name="calculator",
            ),
        ],
    )

    result = ToolSelector().select(request, plan)

    assert result.selected_tools == ["calculator"]


def test_tool_selector_skips_steps_without_tool():
    request = Request(
        user_input="Analyze something"
    )

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Analyze the request.",
            )
        ],
    )

    result = ToolSelector().select(request, plan)

    assert result.selected_tools == []


def test_tool_selector_preserves_request_id():
    capability_registry.register(
        Capability(
            name="calculator",
            description="Performs calculations.",
        )
    )

    request = Request(user_input="Calculate 5 + 5")
    request_id = request.request_id

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Calculate.",
                tool_name="calculator",
            )
        ],
    )

    result = ToolSelector().select(request, plan)

    assert result.request_id == request_id