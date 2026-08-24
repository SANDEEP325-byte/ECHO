from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    success: bool = True
    result: Any = None
    error: str | None = None