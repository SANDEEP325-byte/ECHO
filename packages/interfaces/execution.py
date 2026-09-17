from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    result: Any = None
    error: str | None = None
    requires_confirmation: bool = False
    pending_action: dict[str, Any] | None = None