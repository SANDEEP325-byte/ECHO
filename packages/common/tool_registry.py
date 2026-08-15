from typing import Any
from packages.interfaces.tool import Tool

class ToolRegistry:
    """Registry containing all available ECHO tools."""
    
    def __init__(self) -> None:
        self._tools: dict[str, Tool] ={}
        
    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        
    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)
    
    def list_tools(self) -> list[dict[str, Any]]:
        return [
            tool.definition.to_dict()
            for tool in self._tools.values()
        ]
        
    def execute(self, name: str, **kwargs: Any) -> Any:
        tool = self.get(name)
        
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        
        return tool.execute(**kwargs)
    
tool_registry = ToolRegistry()