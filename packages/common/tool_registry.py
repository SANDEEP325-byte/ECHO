from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_result import ToolResult

class ToolRegistry:
    """Registry containing all available ECHO tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            tool.definition.to_dict()
            for tool in self._tools.values()
        ]

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return the definitions of all registered tools."""
        return self.list_tools()

    def execute(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)

        if tool is None:
            return ToolResult(
                tool_name=name,
                success=False,
                error=f"Unknown tool: {name}",
            )

        try:
            result = tool.execute(**kwargs)

            return ToolResult(
                tool_name=name,
                success=True,
                result=result,
            )

        except Exception as exc:
            return ToolResult(
                tool_name=name,
                success=False,
                error=str(exc),
            )

tool_registry = ToolRegistry()