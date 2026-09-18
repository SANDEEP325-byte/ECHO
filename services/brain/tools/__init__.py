from packages.common.capability_registry import (
    Capability,
    capability_registry,
)
from packages.common.tool_registry import tool_registry
from services.brain.tools.browser_tools import ALL_BROWSER_TOOLS
from services.brain.tools.calculator import calculator_tool
from services.brain.tools.command_tools import ALL_COMMAND_TOOLS
from services.brain.tools.date import date_tool
from services.brain.tools.filesystem_tools import ALL_FILESYSTEM_TOOLS
from services.brain.tools.launch_tools import ALL_LAUNCH_TOOLS
from services.brain.tools.time import time_tool
from services.coding.tools import ALL_CODING_TOOLS


def register_builtin_tools() -> None:
    """Register all built-in ECHO tools."""

    tools = [
        calculator_tool,
        time_tool,
        date_tool,
        *ALL_FILESYSTEM_TOOLS,
        *ALL_LAUNCH_TOOLS,
        *ALL_COMMAND_TOOLS,
        *ALL_BROWSER_TOOLS,
        *ALL_CODING_TOOLS,
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
