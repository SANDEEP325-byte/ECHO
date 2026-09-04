from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    success: bool = True
    result: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        normalized_tool_name = self.tool_name.strip()

        if not normalized_tool_name:
            raise ValueError(
                "Tool result tool name cannot be empty."
            )

        if not isinstance(self.success, bool):
            raise TypeError(
                "Tool result success must be a boolean."
            )

        object.__setattr__(
            self,
            "tool_name",
            normalized_tool_name,
        )