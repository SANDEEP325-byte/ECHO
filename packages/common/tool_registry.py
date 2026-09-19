from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_result import ToolResult
from packages.interfaces.tool_schema import ToolDefinition


class ToolRegistry:
    """Registry containing all available ECHO tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not hasattr(tool, "definition"):
            raise AttributeError(f"Tool '{tool.name}' must define a ToolDefinition.")

        if not isinstance(tool.definition, ToolDefinition):
            raise TypeError(f"Tool '{tool.name}' definition must be a ToolDefinition.")

        if tool.name != tool.definition.name:
            raise ValueError(
                f"Tool name '{tool.name}' does not match definition name '{tool.definition.name}'."
            )

        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if removed, False if not found."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.definition.to_dict() for tool in self._tools.values()]  # type: ignore[attr-defined]

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

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name=name,
                success=False,
                error=str(exc),
            )


tool_registry = ToolRegistry()
