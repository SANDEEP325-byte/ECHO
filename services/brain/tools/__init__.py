from packages.common.capability_registry import (Capability, capability_registry, )
from packages.common.tool_registry import tool_registry
from services.brain.tools.calculator import calculator_tool
from services.brain.tools.time import time_tool
from services.brain.tools.date import date_tool


def register_builtin_tools() -> None:
    """Register all built-in ECHO tools."""

    tools = [
        calculator_tool,
        time_tool,
        date_tool,
    ]

    for tool in tools:
        tool_registry.register(tool)

        capability_registry.register(
            Capability(
                name=tool.name,
                description=tool.description,
            )
        )

register_builtin_tools()