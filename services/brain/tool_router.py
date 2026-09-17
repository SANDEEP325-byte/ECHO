import re
from typing import Any

from packages.common.tool_registry import tool_registry
from packages.interfaces.tool_result import ToolResult
from services.brain.tools import register_builtin_tools
from services.logging.logger import logger


class ToolRouter:
    """Determines and executes tools for ECHO."""
    
    def __init__(self) -> None:
        register_builtin_tools()

    CALCULATION_PATTERN = re.compile(
        r"^[\d\s\+\-\*\/\%\(\)\.\^]+$"
    )

    def extract_calculation(self, message: str) -> str | None:
        message = message.strip()

        # Direct mathematical expression
        if self.CALCULATION_PATTERN.fullmatch(message):
            return message

        patterns = [
            r"^what is\s+(.+?)\??$",
            r"^calculate\s+(.+?)\??$",
            r"^solve\s+(.+?)\??$",
            r"^compute\s+(.+?)\??$",
        ]

        for pattern in patterns:
            match = re.match(
                pattern,
                message,
                re.IGNORECASE,
            )

            if match:
                expression = match.group(1).strip()

                if self.CALCULATION_PATTERN.fullmatch(expression):
                    return expression

        return None

    def should_use_calculator(self, message: str) -> bool:
        return self.extract_calculation(message) is not None

    def should_use_tool(self, tool_name: str, message: str) -> bool:
        """
        Determine whether a specific tool should handle the message.
        """

        if tool_name == "calculator":
            return self.should_use_calculator(message)
        
        if tool_name == "time":
            normalized = message.strip().lower()

            time_patterns = [
                r"^what time is it\??$",
                r"^what's the time\??$",
                r"^whats the time\??$",
                r"^tell me the time\??$",
                r"^current time\??$",
                r"^what is the current time\??$",
                r"^what's the current time\??$",
                r"^whats the current time\??$",
            ]

            return any(
                re.fullmatch(
                    pattern,
                    normalized,
                    re.IGNORECASE,
                )
                for pattern in time_patterns
            )
            
        if tool_name == "date":
            normalized = message.strip().lower()
            
            date_patterns = [
                r"^what is today's date\??$",
                r"^what's today's date\??$",
                r"^whats today's date\??$",
                r"^what is the date today\??$",
                r"^what's the date today\??$",
                r"^whats the date today\??$",
                r"^what date is it\??$",
                r"^tell me today's date\??$",
                r"^tell me the date today\??$",
                r"^what is the current date\??$",
                r"^what's the current date\??$",
                r"^whats the current date\??$",
            ]
            
            return any(
                re.fullmatch(
                    pattern,
                    normalized,
                    re.IGNORECASE,
                )
                for pattern in date_patterns
            )

        return False

    def execute_calculator(self, message: str) -> Any:
        expression = self.extract_calculation(message)

        if expression is None:
            raise ValueError("No valid calculation found.")

        expression = expression.replace("^", "**")

        logger.info(
            "Calculator tool requested: {}",
            expression,
        )

        result = self.execute_tool(
            "calculator",
            expression=expression,
        )

        logger.info(
            "Calculator tool result: {}",
            result,
        )

        return result
    
    def execute_for_intent(
        self,
        intent: str,
        message: str,
    ) -> Any:
        """Execute the tool associated with an intent."""

        tool_name = self.get_tool_for_intent(intent)

        if tool_name is None:
            raise ValueError(
                f"No tool mapped to intent: {intent}"
            )

        if tool_name == "calculator":
            return self.execute_tool(
                tool_name,
                message,
            )

        return self.execute_tool(tool_name)

    def execute_tool(
        self,
        tool_name: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Generic tool execution entry point."""

        tool = tool_registry.get(tool_name)

        if tool is None:
            raise ValueError(
                f"Unknown or unsupported tool: {tool_name}"
            )

        if tool_name == "calculator":
            if "expression" not in kwargs and message is not None:
                expression = self.extract_calculation(message)

                if expression is None:
                    raise ValueError(
                        "No valid calculation found."
                    )

                expression = expression.replace("^", "**")
                kwargs["expression"] = expression

        try:
            result = tool_registry.execute(
                tool_name,
                **kwargs,
            )
        except Exception as exc:
            logger.error(
                "Tool execution failed for '{}': {}",
                tool_name,
                exc,
            )
            raise RuntimeError(
                f"Tool execution failed: {exc}"
            ) from exc

        if isinstance(result, ToolResult):
            if not result.success:
                raise ValueError(
                    result.error or f"Tool execution failed: {tool_name}"
                )

            return result.result
    
        return result
        
    def get_available_tools(self) -> list[dict[str, Any]]:
        """Return definitions of all registered tools."""

        return tool_registry.get_definitions()
    
    def is_tool_registered(self, tool_name: str) -> bool:
        return tool_registry.get(tool_name) is not None
    
    def get_tool_for_intent(self, intent: str) -> str | None:
        """Return the tool name associated with an intent."""

        intent_to_tool = {
            "calculator": "calculator",
            "time": "time",
            "date": "date",
        }

        return intent_to_tool.get(intent)

tool_router = ToolRouter()