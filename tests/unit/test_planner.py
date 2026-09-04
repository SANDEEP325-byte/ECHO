from packages.interfaces.plan import Plan, PlanStep
from services.brain.planner import Planner


def test_direct_request_does_not_require_planning():
    plan = Planner.create_plan(
        "What is Python?",
        requires_planning=False,
    )

    assert isinstance(plan, Plan)
    assert plan.requires_planning is False
    assert plan.steps == []


def test_create_and_run_request_generates_multiple_steps():
    plan = Planner.create_plan(
        "Create a Python project and run it.",
        requires_planning=True,
    )

    assert plan.requires_planning is True
    assert len(plan.steps) == 4

    assert plan.steps[0].step_number == 1
    assert plan.steps[1].step_number == 2
    assert plan.steps[2].step_number == 3
    assert plan.steps[3].step_number == 4
    
    assert plan.steps[0].tool_name == "terminal"
    assert plan.steps[1].tool_name == "terminal"
    assert plan.steps[2].tool_name == "terminal"
    assert plan.steps[3].tool_name is None


def test_multi_step_plan_contains_plan_steps():
    plan = Planner.create_plan(
        "Install the project and configure it.",
        requires_planning=True,
    )

    assert plan.requires_planning is True
    assert len(plan.steps) == 2

    for step in plan.steps:
        assert isinstance(step, PlanStep)
        assert step.step_number > 0
        assert step.description


def test_plan_steps_are_ordered():
    plan = Planner.create_plan(
        "Create and run an application.",
        requires_planning=True,
    )

    numbers = [step.step_number for step in plan.steps]

    assert numbers == [1, 2, 3, 4]
    
def test_non_execution_step_does_not_require_tool():
    plan = Planner.create_plan(
        "Install the project and configure it.",
        requires_planning=True,
    )

    assert plan.steps[0].tool_name is None
    assert plan.steps[1].tool_name is None