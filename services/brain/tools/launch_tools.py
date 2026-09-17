from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.desktop.app_launcher import desktop_app_launcher
from services.desktop.filesystem import filesystem_service


class OpenFileTool(Tool):
    name = "open_file"
    description = "Opens an authorized file with its default associated application."

    definition = ToolDefinition(
        name="open_file",
        description="Opens an authorized file with its default associated application.",
        parameters=(
            ToolParameter(
                name="path",
                type="string",
                description="The path of the file to open.",
                required=True,
            ),
        ),
    )

    def execute(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return filesystem_service.open_file(path=path)


class OpenFolderTool(Tool):
    name = "open_folder"
    description = "Opens an authorized folder in the desktop file explorer."

    definition = ToolDefinition(
        name="open_folder",
        description="Opens an authorized folder in the desktop file explorer.",
        parameters=(
            ToolParameter(
                name="path",
                type="string",
                description="The path of the folder to open.",
                required=True,
            ),
        ),
    )

    def execute(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return filesystem_service.open_folder(path=path)


class OpenApplicationTool(Tool):
    name = "open_application"
    description = "Launches an allowlisted desktop application by name (e.g. 'notepad', 'calculator')."

    definition = ToolDefinition(
        name="open_application",
        description="Launches an allowlisted desktop application by name (e.g. 'notepad', 'calculator').",
        parameters=(
            ToolParameter(
                name="application_name",
                type="string",
                description="The name of the allowlisted application to launch.",
                required=True,
            ),
        ),
    )

    def execute(
        self,
        application_name: str | None = None,
        name: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        app_name = application_name or name
        if not app_name:
            raise ValueError("Tool 'open_application' requires parameter 'application_name'.")
        return desktop_app_launcher.launch_application(application_name=str(app_name))


open_file_tool = OpenFileTool()
open_folder_tool = OpenFolderTool()
open_application_tool = OpenApplicationTool()

ALL_LAUNCH_TOOLS = [
    open_file_tool,
    open_folder_tool,
    open_application_tool,
]
