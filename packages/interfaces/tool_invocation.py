from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class ToolInvocation:
    """Represents a structured tool invocation within Project ECHO."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    purpose: str | None = None
    step_number: int | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_name or not self.tool_name.strip():
            raise ValueError("Tool name cannot be empty.")
        if not re.fullmatch(r"[a-zA-Z0-9_\-]+", self.tool_name.strip()):
            raise ValueError("Invalid tool name format.")
        if not isinstance(self.arguments, dict):
            raise ValueError("Arguments must be a dictionary.")

        # Canonicalize tool name
        object.__setattr__(self, "tool_name", self.tool_name.strip().lower())

        is_valid, err = self.validate()
        if not is_valid:
            raise ValueError(err)

    def validate(self) -> tuple[bool, str | None]:
        """Validate the tool invocation parameters against safety and schema boundaries."""
        name = self.tool_name.strip().lower()

        if name == "calculator":
            if "expression" not in self.arguments:
                return False, "Calculator invocation requires 'expression'."
            expr = self.arguments.get("expression")
            if not isinstance(expr, str):
                return False, "Calculator expression must be a string."
            if not expr.strip():
                return False, "Calculator requires a non-empty string expression."
            # Whitelist valid math characters
            if not re.fullmatch(r"[\d\s\+\-\*\/\%\(\)\.\^\*]+", expr.strip()):
                return False, f"Calculator expression contains unsafe or invalid characters: '{expr}'."

        return True, None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "purpose": self.purpose,
            "step_number": self.step_number,
        }
