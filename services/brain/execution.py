from packages.interfaces.execution import ExecutionResult
from packages.interfaces.plan import Plan
from packages.interfaces.request import Request, RequestStatus
from services.brain.tool_router import ToolRouter
from services.logging.logger import logger
from packages.interfaces.security import PermissionDecision
from services.security.safety_engine import SafetyEngine


class ExecutionEngine:
    """Executes a request plan through ECHO's tool routing layer."""

    def __init__(
        self,
        router: ToolRouter | None = None,
        safety_engine: SafetyEngine | None = None,
    ) -> None:
        self.router = router or ToolRouter()
        self.safety_engine = safety_engine or SafetyEngine()

    def execute(
        self,
        request: Request,
        plan: Plan,
    ) -> ExecutionResult:
        logger.info(
            "Starting execution for request {}",
            request.request_id,
        )

        request.status = RequestStatus.EXECUTING

        if not plan.requires_planning:
            logger.info(
                "Request {} has no execution plan",
                request.request_id,
            )

            return ExecutionResult(
                success=True,
                result=None,
            )

        if not plan.steps:
            return ExecutionResult(
                success=False,
                error="Execution plan contains no steps.",
            )

        if not request.selected_tools:
            return ExecutionResult(
                success=False,
                error="No tools selected for execution.",
            )

        results = []

        for step in plan.steps:
            logger.info(
                "Executing request {} step {}: {}",
                request.request_id,
                step.step_number,
                step.description,
            )

            tool_name = step.tool_name

            if tool_name is None:
                logger.info(
                    "Request {} step {} requires no tool",
                    request.request_id,
                    step.step_number,
                )

                results.append(
                    f"Step {step.step_number} completed."
                )

                continue

            if tool_name not in request.selected_tools:
                request.status = RequestStatus.FAILED

                return ExecutionResult(
                    success=False,
                    error=(
                        f"Tool '{tool_name}' required by step "
                        f"{step.step_number} was not selected."
                    ),
                )

            try:
                safety_result = self.safety_engine.evaluate(tool_name)
            except Exception as exc:
                logger.error(
                    "Request {} step {} safety evaluation failed: {}",
                    request.request_id,
                    step.step_number,
                    exc,
                )

                request.status = RequestStatus.FAILED

                return ExecutionResult(
                    success=False,
                    error=str(exc),
                )

            if safety_result.decision == PermissionDecision.BLOCK:
                request.status = RequestStatus.FAILED

                return ExecutionResult(
                    success=False,
                    error=(
                        f"Operation '{tool_name}' was blocked by "
                        f"the security policy."
                    ),
                )

            if safety_result.decision == PermissionDecision.CONFIRM:
                request.status = RequestStatus.FAILED

                return ExecutionResult(
                    success=False,
                    error=(
                        f"User confirmation is required before executing "
                        f"'{tool_name}'."
                    ),
                )

            try:
                result = self.router.execute_tool(
                    tool_name,
                    request.user_input,
                )

                results.append(result)

                logger.info(
                    "Security decision for request {} step {}: operation={}, risk={}, decision={}",
                    request.request_id,
                    step.step_number,
                    safety_result.operation,
                    safety_result.risk_level.value,
                    safety_result.decision.value,
                )

                logger.info(
                    "Request {} step {} completed successfully",
                    request.request_id,
                    step.step_number,
                )

            except Exception as exc:
                logger.error(
                    "Request {} step {} failed: {}",
                    request.request_id,
                    step.step_number,
                    exc,
                )

                request.status = RequestStatus.FAILED

                return ExecutionResult(
                    success=False,
                    error=str(exc),
                )

        request.status = RequestStatus.COMPLETED

        logger.info(
            "Execution completed for request {}",
            request.request_id,
        )

        return ExecutionResult(
            success=True,
            result=results,
        )


execution_engine = ExecutionEngine()