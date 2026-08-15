from packages.common.tool_registry import tool_registry
from services.brain.tools.calculator import calculator_tool


tool_registry.register(calculator_tool)