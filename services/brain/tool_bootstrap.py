from packages.common.tool_registry import tool_registry
from services.brain.tools.calculator import calculator_tool
from services.brain.tools.time import time_tool
from services.brain.tools.date import date_tool
from services.brain.tools.filesystem_tools import ALL_FILESYSTEM_TOOLS


def register_builtin_tools() -> None:
    """Register all built-in ECHO tools."""

    tool_registry.register(calculator_tool)
    tool_registry.register(time_tool)
    tool_registry.register(date_tool)
    for tool in ALL_FILESYSTEM_TOOLS:
        tool_registry.register(tool)