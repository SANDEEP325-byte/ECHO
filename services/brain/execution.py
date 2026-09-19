from packages.interfaces.execution import ExecutionResult
from packages.interfaces.pending_action import (
    ConfirmationResult,
    ConfirmationStatus,
)
from packages.interfaces.plan import Plan
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.security import PermissionDecision
from packages.interfaces.tool_invocation import ToolInvocation
from services.brain.tool_router import ToolRouter
from services.brain.verification import (
    VerificationEngine,
)
from services.brain.verification import (
    verification_engine as default_verification_engine,
)
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.security.pending_action_manager import (
    PendingActionManager,
)
from services.security.pending_action_manager import (
    pending_action_manager as default_pending_action_manager,
)
from services.security.safety_engine import SafetyEngine


class ExecutionEngine:
    """Executes a request plan through ECHO's tool routing layer."""

    def __init__(
        self,
        router: ToolRouter | None = None,
        safety_engine: SafetyEngine | None = None,
        pending_action_manager: PendingActionManager | None = None,
        verification_engine: VerificationEngine | None = None,
    ) -> None:
        self.router = router or ToolRouter()
        self.safety_engine = safety_engine or SafetyEngine()
        self.pending_action_manager = pending_action_manager or default_pending_action_manager
        self.verification_engine = verification_engine or default_verification_engine

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

                results.append(f"Step {step.step_number} completed.")

                continue

            if tool_name not in request.selected_tools:
                request.status = RequestStatus.FAILED

                return ExecutionResult(
                    success=False,
                    error=(
                        f"Tool '{tool_name}' required by step {step.step_number} was not selected."
                    ),
                )

            step_args = getattr(step, "arguments", {}) or {}
            try:
                try:
                    safety_result = self.safety_engine.evaluate(
                        tool_name,
                        arguments=step_args,
                    )
                except TypeError as type_err:
                    if "unexpected keyword argument" in str(type_err):
                        safety_result = self.safety_engine.evaluate(tool_name)
                    else:
                        raise
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
                    error=(f"Operation '{tool_name}' was blocked by the security policy."),
                )

            if safety_result.decision == PermissionDecision.CONFIRM:
                request.status = RequestStatus.FAILED

                action = self.pending_action_manager.create_pending_action(
                    tool_name=tool_name,
                    arguments=step_args,
                    risk_level=safety_result.risk_level,
                    request_id=request.request_id,
                    step_number=step.step_number,
                    session_id=request.session_id,
                )

                return ExecutionResult(
                    success=False,
                    requires_confirmation=True,
                    pending_action=action.to_dict(),
                    error=(f"User confirmation is required before executing '{tool_name}'."),
                )

            try:
                result = self.router.execute_tool(
                    tool_name,
                    request.user_input,
                    **step_args,
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

    def resume_pending_action(
        self,
        action_id: str,
        session_id: str | None = None,
    ) -> ConfirmationResult:
        """Execute a previously confirmed pending action through the security and tool pipeline.

        Guarantees:
        1. Explicit reference to exact action_id (no heuristic guessing).
        2. Atomic single-use claiming (replay & race condition prevention).
        3. Mandatory safety re-check (SafetyEngine & ToolInvocation validation).
        4. Structured non-leaking response.
        5. Session binding enforcement for voice-bound actions.
        """
        claimed, action, status, message = self.pending_action_manager.claim_for_execution(
            action_id, session_id=session_id
        )
        if not claimed or action is None:
            return ConfirmationResult(
                success=False,
                status=status,
                action_id=action_id,
                message=message,
                pending_action=action.to_dict() if action else None,
            )

        # 0. Verify plugin active status if this is a plugin tool
        if "." in action.tool_name:
            plugin_id = action.tool_name.split(".", 1)[0]
            from services.plugins import plugin_manager

            if not plugin_manager.is_plugin_active(plugin_id):
                self.pending_action_manager.mark_failed(
                    action_id, f"Plugin '{plugin_id}' is not active or has been disabled."
                )
                return ConfirmationResult(
                    success=False,
                    status=ConfirmationStatus.FAILED,
                    action_id=action_id,
                    message=f"Cannot resume confirmed action: plugin '{plugin_id}' is not active.",
                    error=f"Plugin '{plugin_id}' is not active.",
                    pending_action=action.to_dict(),
                )

        # 1. Re-validate ToolInvocation parameters
        try:
            invocation = ToolInvocation(
                tool_name=action.tool_name,
                arguments=action.arguments,
                request_id=action.request_id,
                step_number=action.step_number,
            )
            is_valid, validation_err = invocation.validate()
            if not is_valid:
                self.pending_action_manager.mark_failed(
                    action_id, validation_err or "Invalid tool invocation"
                )
                return ConfirmationResult(
                    success=False,
                    status=ConfirmationStatus.FAILED,
                    action_id=action_id,
                    message=f"Action parameter validation failed: {validation_err}",
                    error=validation_err,
                    pending_action=action.to_dict(),
                )
        except Exception as exc:
            self.pending_action_manager.mark_failed(action_id, str(exc))
            return ConfirmationResult(
                success=False,
                status=ConfirmationStatus.FAILED,
                action_id=action_id,
                message=f"Action validation failed: {exc}",
                error=str(exc),
                pending_action=action.to_dict(),
            )

        # 2. Safety Re-check (Requirement 7: confirmation does not bypass security)
        try:
            safety_result = self.safety_engine.evaluate(
                action.tool_name,
                arguments=action.arguments,
            )
        except Exception as exc:
            self.pending_action_manager.mark_failed(action_id, str(exc))
            return ConfirmationResult(
                success=False,
                status=ConfirmationStatus.FAILED,
                action_id=action_id,
                message=f"Safety evaluation failed: {exc}",
                error=str(exc),
                pending_action=action.to_dict(),
            )

        if safety_result.decision == PermissionDecision.BLOCK:
            self.pending_action_manager.mark_failed(
                action_id, "Operation blocked by security policy"
            )
            return ConfirmationResult(
                success=False,
                status=ConfirmationStatus.FAILED,
                action_id=action_id,
                message="Operation was blocked by the security policy.",
                error="Operation was blocked by the security policy.",
                pending_action=action.to_dict(),
            )

        # 3. Route execution through existing ToolRouter
        try:
            result = self.router.execute_tool(
                action.tool_name,
                message=None,
                **action.arguments,
            )
        except Exception as exc:
            logger.error("Confirmed action {} execution failed: {}", action_id, exc)
            self.pending_action_manager.mark_failed(action_id, str(exc))
            return ConfirmationResult(
                success=False,
                status=ConfirmationStatus.FAILED,
                action_id=action_id,
                message="Tool execution failed.",
                error=str(exc),
                pending_action=action.to_dict(),
            )

        # 4. Mark executed (ensures single-use and prevents replay)
        self.pending_action_manager.mark_executed(action_id, result=result)

        # 5. Evaluate post-condition verification
        v_req = Request(user_input=f"Resumed action {action.tool_name}")
        v_exec_res = ExecutionResult(success=True, result=result)
        try:
            v_res = self.verification_engine.verify(v_req, v_exec_res)
        except Exception as exc:
            logger.error("Verification exception on confirmed action {}: {}", action_id, exc)
            return ConfirmationResult(
                success=False,
                status=ConfirmationStatus.CONFIRMED,
                action_id=action_id,
                message=f"Action executed, but verification encountered an error: {exc}",
                error=str(exc),
                result=result,
                pending_action=action.to_dict(),
            )

        if not v_res.success:
            logger.warning(
                "Confirmed action {} executed, but post-condition was not verified: {}",
                action_id,
                v_res.error,
            )
            return ConfirmationResult(
                success=False,
                status=ConfirmationStatus.CONFIRMED,
                action_id=action_id,
                message=v_res.error or "Action executed, but post-condition verification failed.",
                error=v_res.error,
                result=result,
                pending_action=action.to_dict(),
                verification=v_res,
            )

        return ConfirmationResult(
            success=True,
            status=ConfirmationStatus.CONFIRMED,
            action_id=action_id,
            message="Action confirmed, executed, and verified successfully.",
            result=result,
            pending_action=action.to_dict(),
            verification=v_res,
        )

    def cancel_pending_action(
        self,
        action_id: str,
        session_id: str | None = None,
    ) -> ConfirmationResult:
        """Cancel a pending action, permanently preventing execution."""
        return self.pending_action_manager.cancel_action(action_id, session_id=session_id)


execution_engine = ExecutionEngine()
