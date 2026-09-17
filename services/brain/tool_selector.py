from typing import Any

from packages.common.capability_registry import capability_registry
from packages.interfaces.plan import Plan
from packages.interfaces.request import Request
from packages.interfaces.tool_invocation import ToolInvocation
from services.brain.tool_router import tool_router
from services.logging.logger import logger


class ToolSelector:
    """Unifies tool selection and builds validated ToolInvocation models."""

    def select(
        self,
        request: Request,
        plan: Plan,
    ) -> Request:
        """Legacy helper for setting request.selected_tools from a plan."""
        logger.info(
            "Selecting tools for request {}",
            request.request_id,
        )

        selected_tools: list[str] = []

        for step in plan.steps:
            tool_name = step.tool_name

            if tool_name is None:
                continue

            if not capability_registry.is_available(tool_name):
                logger.warning(
                    "Required capability unavailable for request {}: {}",
                    request.request_id,
                    tool_name,
                )
                continue

            if tool_name not in selected_tools:
                selected_tools.append(tool_name)

        request.selected_tools = selected_tools

        logger.info(
            "Tools selected for request {}: {}",
            request.request_id,
            selected_tools,
        )

        return request

    def select_invocations(
        self,
        request_or_plan: Any,
        plan: Plan | None = None,
    ) -> list[ToolInvocation]:
        """Builds validated ToolInvocation objects for each plan step."""
        if plan is None and isinstance(request_or_plan, Plan):
            actual_plan = request_or_plan
            request_id = None
        else:
            actual_plan = plan or Plan(requires_planning=False, steps=[])
            request_id = getattr(request_or_plan, "request_id", None)

        invocations: list[ToolInvocation] = []

        for step in actual_plan.steps:
            if not step.tool_name:
                continue

            if not capability_registry.is_available(step.tool_name):
                logger.warning(
                    "Capability '{}' required by step {} is not available in registry",
                    step.tool_name,
                    step.step_number,
                )
                continue

            try:
                invocation = ToolInvocation(
                    tool_name=step.tool_name,
                    arguments=dict(step.arguments) if step.arguments else {},
                    purpose=step.purpose,
                    request_id=request_id,
                    step_number=step.step_number,
                )
                invocations.append(invocation)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Tool invocation validation failed for step {}: {}",
                    step.step_number,
                    exc,
                )

        return invocations

    @staticmethod
    def select_single_tool(
        intent_or_tool: str,
        message_or_args: Any = None,
        request_id: str | None = None,
        purpose: str | None = None,
    ) -> ToolInvocation | None:
        """Generates a structured ToolInvocation for a single-tool intent or explicit capability."""
        name_lower = intent_or_tool.lower().strip()

        if isinstance(message_or_args, dict):
            if not capability_registry.is_available(name_lower):
                return None
            try:
                return ToolInvocation(
                    tool_name=name_lower,
                    arguments=dict(message_or_args),
                    purpose=purpose,
                    request_id=request_id,
                )
            except Exception:
                return None

        message = str(message_or_args or "")

        if name_lower == "calculator":
            expr = tool_router.extract_calculation(message)
            if expr:
                expr = expr.replace("^", "**")
                try:
                    return ToolInvocation(
                        tool_name="calculator",
                        arguments={"expression": expr},
                        purpose=purpose,
                        request_id=request_id,
                    )
                except Exception:
                    return None

        if name_lower in {"time", "date"}:
            try:
                return ToolInvocation(
                    tool_name=name_lower,
                    arguments={},
                    purpose=purpose,
                    request_id=request_id,
                )
            except Exception:
                return None

        return None


tool_selector = ToolSelector()