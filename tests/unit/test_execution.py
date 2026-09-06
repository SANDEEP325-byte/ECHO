import pytest
from packages.interfaces.execution import ExecutionResult
from packages.interfaces.plan import  Plan, PlanStep
from packages.interfaces.request import Request, RequestStatus
from services.brain.execution import ExecutionEngine
from packages.interfaces.security import (
    PermissionDecision,
    RiskLevel,
    SafetyResult,
)

def test_execution_result_represents_success():
    result = ExecutionResult(
        success = True,
        result= "done",
    )

    assert result.success is True
    assert result.result == "done"
    assert result.error is None

def test_execution_resullt_represents_failure():
    result = ExecutionResult(
        success= False,
        error= "Permission denied",
    )

    assert result.success is False
    assert result.error == "Permission denied"

def test_execution_without_plan_succeeds():
    engine = ExecutionEngine()

    request = Request(
        user_input="What is Python?"
    )

    plan = Plan(
        requires_planning=False,
        steps=[],
    )

    result =  engine.execute(
        request,
        plan,
    )

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert request.status == RequestStatus.EXECUTING

def test_execution_fails_when_required_tool_is_unavailable():
    engine = ExecutionEngine()

    request = Request(
        user_input="Create and run an application."
    )

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Create the application.",
                tool_name="terminal",
            ),
            PlanStep(
                step_number=2,
                description="Run the application.",
                tool_name="terminal",
            ),
        ],
    )

    request.selected_tools = ["terminal"]

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is False
    assert result.error == "Unknown or unsupported tool: terminal"
    assert request.status == RequestStatus.FAILED

def test_exection_preserves_request_id():
    engine = ExecutionEngine()

    request = Request(
        user_input="Run a task"
    )

    request_id = request.request_id

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Execute task.",
            ),
        ],
    )

    engine.execute(
        request,
        plan
    )

    assert request.request_id == request_id

def test_execution_uses_tool_defined_by_each_plan_step():
    engine = ExecutionEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    request.selected_tools = [
        "calculator",
        "time",
    ]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Perform calculation.",
                tool_name="calculator",
            ),
            PlanStep(
                step_number=2,
                description="Get current time.",
                tool_name="time",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is True
    assert len(result.result) == 2


def test_execution_skips_steps_without_tool():
    engine = ExecutionEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    request.selected_tools = ["calculator"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Perform calculation.",
                tool_name="calculator",
            ),
            PlanStep(
                step_number=2,
                description="Verify the result.",
                tool_name=None,
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is True
    assert len(result.result) == 2
    assert result.result[0] == 15
    assert result.result[1] == "Step 2 completed."

def test_execution_marks_request_completed_on_success():
    engine = ExecutionEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    request.selected_tools = ["calculator"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Perform calculation.",
                tool_name="calculator",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is True
    assert request.status == RequestStatus.COMPLETED

class FakeSafetyEngine:
    def __init__(
        self,
        decision: PermissionDecision,
        risk_level: RiskLevel,
    ) -> None:
        self.decision = decision
        self.risk_level = risk_level

    def evaluate(self, operation: str) -> SafetyResult:
        return SafetyResult(
            decision=self.decision,
            risk_level=self.risk_level,
            reason="Test safety decision.",
            operation=operation,
        )


def test_execution_allows_safe_operation():
    safety_engine = FakeSafetyEngine(
        PermissionDecision.ALLOW,
        RiskLevel.SAFE,
    )

    engine = ExecutionEngine(
        safety_engine=safety_engine,
    )

    request = Request(
        user_input="Calculate 10 + 5",
    )

    request.selected_tools = ["calculator"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Perform calculation.",
                tool_name="calculator",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is True
    assert result.result == [15]


def test_execution_stops_when_confirmation_is_required():
    safety_engine = FakeSafetyEngine(
        PermissionDecision.CONFIRM,
        RiskLevel.SENSITIVE,
    )

    engine = ExecutionEngine(
        safety_engine=safety_engine,
    )

    request = Request(
        user_input="Delete the file.",
    )

    request.selected_tools = ["delete_file"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Delete the file.",
                tool_name="delete_file",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is False
    assert result.error == (
        "User confirmation is required before executing "
        "'delete_file'."
    )
    assert request.status == RequestStatus.FAILED


def test_execution_blocks_critical_operation():
    safety_engine = FakeSafetyEngine(
        PermissionDecision.BLOCK,
        RiskLevel.CRITICAL,
    )

    engine = ExecutionEngine(
        safety_engine=safety_engine,
    )

    request = Request(
        user_input="Format the drive.",
    )

    request.selected_tools = ["format_drive"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Format the drive.",
                tool_name="format_drive",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is False
    assert result.error == (
        "Operation 'format_drive' was blocked by "
        "the security policy."
    )
    assert request.status == RequestStatus.FAILED

# SENSITIVE OPERATION
def test_execution_blocks_sensitive_operation_without_confirmation():
    engine = ExecutionEngine()

    request = Request(
        user_input="Delete my file",
    )

    request.selected_tools = ["delete_file"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Delete the requested file.",
                tool_name="delete_file",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is False
    assert result.error == (
        "User confirmation is required before executing 'delete_file'."
    )
    assert request.status == RequestStatus.FAILED

# CRITICAL OPERATION
def test_execution_blocks_critical_operation_without_confirmation():
    engine = ExecutionEngine()

    request = Request(
        user_input="Format the drive",
    )

    request.selected_tools = ["format_drive"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Format the drive.",
                tool_name="format_drive",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is False
    assert result.error == (
        "User confirmation is required before executing 'format_drive'."
    )
    assert request.status == RequestStatus.FAILED

# SAFE OPERATION
def test_execution_allows_safe_operation():
    engine = ExecutionEngine()

    request = Request(
        user_input="Calculate 10 + 5",
    )

    request.selected_tools = ["calculator"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Perform calculation.",
                tool_name="calculator",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is True
    assert result.result == [15]
    assert request.status == RequestStatus.COMPLETED

def test_execution_evaluates_security_once_per_tool_step():
    class CountingSafetyEngine:
        def __init__(self):
            self.calls = []

        def evaluate(self, operation: str) -> SafetyResult:
            self.calls.append(operation)

            return SafetyResult(
                decision=PermissionDecision.ALLOW,
                risk_level=RiskLevel.SAFE,
                reason="Allowed for testing.",
                operation=operation,
            )

    class FakeToolRouter:
        def execute_tool(
            self,
            tool_name: str,
            user_input: str,
        ):
            return f"{tool_name} executed"

    safety_engine = CountingSafetyEngine()
    router = FakeToolRouter()

    engine = ExecutionEngine(
        router=router,
        safety_engine=safety_engine,
    )

    request = Request(
        user_input="Perform the requested operations.",
    )

    request.selected_tools = [
        "calculator",
        "time",
    ]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Perform calculation.",
                tool_name="calculator",
            ),
            PlanStep(
                step_number=2,
                description="Get current time.",
                tool_name="time",
            ),
        ],
    )

    result = engine.execute(
        request,
        plan,
    )

    assert result.success is True

    assert safety_engine.calls == [
        "calculator",
        "time",
    ]

def test_execution_propagates_safety_engine_exception():
    class FailingSafetyEngine:
        def evaluate(self, operation: str) -> SafetyResult:
            raise RuntimeError("Safety engine crashed.")

    engine = ExecutionEngine(
        safety_engine=FailingSafetyEngine(),
    )

    request = Request(
        user_input="Calculate 10 + 5",
    )

    request.selected_tools = ["calculator"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Perform calculation.",
                tool_name="calculator",
            ),
        ],
    )

    result = engine.execute(request, plan)

    assert result.success is False
    assert result.error == "Safety engine crashed."
    assert request.status == RequestStatus.FAILED
