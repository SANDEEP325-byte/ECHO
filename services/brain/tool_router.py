import re
from typing import Any
from packages.common.tool_registry import tool_registry
from services.brain import tools
from services.logging.logger import logger

class ToolRouter:
    """Determines whether a user request should use an ECHO tool."""

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

    def execute_calculator(self, message: str) -> Any:
        expression = self.extract_calculation(message)

        if expression is None:
            raise ValueError("No valid calculation found.")

        expression = expression.replace("^", "**")

        logger.info(
            "Calculator tool requested: {}",
            expression,
        )

        result = tool_registry.execute(
            "calculator",
            expression=expression,
        )

        logger.info(
            "Calculator tool result: {}",
            result,
        )

        return result

tool_router = ToolRouter()