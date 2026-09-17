from typing import Any, Sequence

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.desktop.commands import command_executor


class ExecuteCommandTool(Tool):
    name = "execute_command"
    description = "Executes an authorized, controlled system command (e.g. git status, python --version)."

    definition = ToolDefinition(
        name="execute_command",
        description="Executes an authorized, controlled system command (e.g. git status, python --version).",
        parameters=(
            ToolParameter(
                name="command",
                type="string",
                description="The allowlisted command family to execute ('git', 'python').",
                required=True,
            ),
            ToolParameter(
                name="arguments",
                type="array",
                description="List of safe arguments for the command.",
                required=False,
            ),
            ToolParameter(
                name="cwd",
                type="string",
                description="Optional working directory inside authorized sandbox roots.",
                required=False,
            ),
        ),
    )

    def execute(
        self,
        command: str | None = None,
        arguments: Sequence[str] | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cmd = command or kwargs.get("name")
        if not cmd:
            raise ValueError("Tool 'execute_command' requires parameter 'command'.")
        return command_executor.execute_command(
            command=str(cmd),
            arguments=arguments,
            cwd=cwd,
        )


execute_command_tool = ExecuteCommandTool()

ALL_COMMAND_TOOLS = [
    execute_command_tool,
]
