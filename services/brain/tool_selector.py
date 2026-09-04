from packages.interfaces.plan import Plan
from packages.interfaces.request import Request
from packages.common.capability_registry import capability_registry
from services.logging.logger import logger


class ToolSelector:
    """Selects available tools required by a request plan."""

    def select(
        self,
        request: Request,
        plan: Plan,
    ) -> Request:
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


tool_selector = ToolSelector()