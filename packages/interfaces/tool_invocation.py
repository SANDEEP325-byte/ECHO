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

        if name in {
            "read_file",
            "list_folder",
            "create_folder",
            "create_file",
            "delete_file",
            "open_file",
            "open_folder",
        }:
            if "path" not in self.arguments:
                return False, f"Tool '{name}' invocation requires 'path'."
            path_val = self.arguments.get("path")
            if not isinstance(path_val, str) or not path_val.strip():
                return False, f"Tool '{name}' requires a non-empty string 'path'."

        if name in {"copy_file", "rename_file", "move_file"}:
            if "source" not in self.arguments:
                return False, f"Tool '{name}' invocation requires 'source'."
            src_val = self.arguments.get("source")
            if not isinstance(src_val, str) or not src_val.strip():
                return False, f"Tool '{name}' requires a non-empty string 'source'."

            if "destination" not in self.arguments:
                return False, f"Tool '{name}' invocation requires 'destination'."
            dst_val = self.arguments.get("destination")
            if not isinstance(dst_val, str) or not dst_val.strip():
                return False, f"Tool '{name}' requires a non-empty string 'destination'."

        if name == "open_application":
            app_val = self.arguments.get("application_name") or self.arguments.get("name")
            if not app_val:
                return False, "Tool 'open_application' invocation requires 'application_name'."
            if not isinstance(app_val, str) or not app_val.strip():
                return False, "Tool 'open_application' requires a non-empty string 'application_name'."
            if any(c in app_val for c in ("/\\:*?\"<>|\x00")):
                return False, f"Invalid application name '{app_val}': paths and special characters are prohibited."
            if app_val.strip().lower().endswith((".exe", ".bat", ".cmd", ".ps1", ".vbs", ".sh", ".py", ".msi", ".com")):
                return False, f"Executable/script extensions are prohibited in application name: '{app_val}'."

        if name in {"execute_command", "run_command"}:
            cmd_val = self.arguments.get("command") or self.arguments.get("name")
            if not cmd_val:
                return False, f"Tool '{name}' invocation requires 'command'."
            if not isinstance(cmd_val, str) or not cmd_val.strip():
                return False, f"Tool '{name}' requires a non-empty string 'command'."
            if any(c in cmd_val for c in ("/\\:*?\"<>|\x00&;`$")):
                return False, f"Invalid command identifier '{cmd_val}': path separators and shell metacharacters are prohibited."
            if "arguments" in self.arguments:
                args_val = self.arguments.get("arguments")
                if args_val is not None:
                    if not isinstance(args_val, (list, tuple)):
                        return False, f"Tool '{name}' requires 'arguments' to be a list of strings, not a command string."
                    for arg in args_val:
                        if not isinstance(arg, str):
                            return False, f"Tool '{name}' argument must be a string, got {type(arg).__name__}."
                        if any(c in arg for c in ("&", "|", ";", ">", "<", "`", "$", "\x00")):
                            return False, f"Forbidden shell metacharacter detected in argument: '{arg}'."
            if "cwd" in self.arguments:
                cwd_val = self.arguments.get("cwd")
                if cwd_val is not None and (not isinstance(cwd_val, str) or not cwd_val.strip()):
                    return False, f"Tool '{name}' parameter 'cwd' must be a non-empty string."

        return True, None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "purpose": self.purpose,
            "step_number": self.step_number,
        }
