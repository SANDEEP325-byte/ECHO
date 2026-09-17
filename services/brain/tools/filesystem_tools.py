from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.desktop.filesystem import filesystem_service


class ReadFileTool(Tool):
    name = "read_file"
    description = "Reads content from a text file within authorized folders."

    definition = ToolDefinition(
        name="read_file",
        description="Reads content from a text file within authorized folders.",
        parameters=(
            ToolParameter(
                name="path",
                type="string",
                description="The path of the file to read.",
                required=True,
            ),
        ),
    )

    def execute(self, path: str, max_bytes: int = 65536, encoding: str = "utf-8", **kwargs: Any) -> str:
        return filesystem_service.read_file(path=path, max_bytes=max_bytes, encoding=encoding)


class ListFolderTool(Tool):
    name = "list_folder"
    description = "Lists files and subdirectories in an authorized folder."

    definition = ToolDefinition(
        name="list_folder",
        description="Lists files and subdirectories in an authorized folder.",
        parameters=(
            ToolParameter(
                name="path",
                type="string",
                description="The path of the folder to list.",
                required=True,
            ),
        ),
    )

    def execute(self, path: str, include_hidden: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        return filesystem_service.list_folder(path=path, include_hidden=include_hidden)


class CreateFolderTool(Tool):
    name = "create_folder"
    description = "Creates a new folder inside an authorized directory."

    definition = ToolDefinition(
        name="create_folder",
        description="Creates a new folder inside an authorized directory.",
        parameters=(
            ToolParameter(
                name="path",
                type="string",
                description="The path of the folder to create.",
                required=True,
            ),
        ),
    )

    def execute(self, path: str, exist_ok: bool = False, **kwargs: Any) -> dict[str, Any]:
        return filesystem_service.create_folder(path=path, exist_ok=exist_ok)


class CreateFileTool(Tool):
    name = "create_file"
    description = "Creates a new file with text content in an authorized folder."

    definition = ToolDefinition(
        name="create_file",
        description="Creates a new file with text content in an authorized folder.",
        parameters=(
            ToolParameter(
                name="path",
                type="string",
                description="The destination path for the new file.",
                required=True,
            ),
            ToolParameter(
                name="content",
                type="string",
                description="The text content to write into the file.",
                required=False,
            ),
        ),
    )

    def execute(self, path: str, content: str = "", overwrite: bool = False, **kwargs: Any) -> dict[str, Any]:
        return filesystem_service.create_file(path=path, content=content, overwrite=overwrite)


class CopyFileTool(Tool):
    name = "copy_file"
    description = "Copies a file from a source location to a destination within authorized folders."

    definition = ToolDefinition(
        name="copy_file",
        description="Copies a file from a source location to a destination within authorized folders.",
        parameters=(
            ToolParameter(
                name="source",
                type="string",
                description="The path of the source file to copy.",
                required=True,
            ),
            ToolParameter(
                name="destination",
                type="string",
                description="The destination path for the copied file.",
                required=True,
            ),
        ),
    )

    def execute(self, source: str, destination: str, overwrite: bool = False, **kwargs: Any) -> dict[str, Any]:
        return filesystem_service.copy_file(source=source, destination=destination, overwrite=overwrite)


class RenameFileTool(Tool):
    name = "rename_file"
    description = "Renames a file or folder within authorized folders."

    definition = ToolDefinition(
        name="rename_file",
        description="Renames a file or folder within authorized folders.",
        parameters=(
            ToolParameter(
                name="source",
                type="string",
                description="The current path of the file or folder.",
                required=True,
            ),
            ToolParameter(
                name="destination",
                type="string",
                description="The new path or name for the file or folder.",
                required=True,
            ),
        ),
    )

    def execute(self, source: str, destination: str, overwrite: bool = False, **kwargs: Any) -> dict[str, Any]:
        return filesystem_service.rename_file(source=source, destination=destination, overwrite=overwrite)


class MoveFileTool(Tool):
    name = "move_file"
    description = "Moves a file or folder from a source to a destination within authorized folders."

    definition = ToolDefinition(
        name="move_file",
        description="Moves a file or folder from a source to a destination within authorized folders.",
        parameters=(
            ToolParameter(
                name="source",
                type="string",
                description="The current path of the file or folder.",
                required=True,
            ),
            ToolParameter(
                name="destination",
                type="string",
                description="The target destination path.",
                required=True,
            ),
        ),
    )

    def execute(self, source: str, destination: str, overwrite: bool = False, **kwargs: Any) -> dict[str, Any]:
        return filesystem_service.move_file(source=source, destination=destination, overwrite=overwrite)


class DeleteFileTool(Tool):
    name = "delete_file"
    description = "Deletes a file or an empty directory within authorized folders. Requires user confirmation."

    definition = ToolDefinition(
        name="delete_file",
        description="Deletes a file or an empty directory within authorized folders. Requires user confirmation.",
        parameters=(
            ToolParameter(
                name="path",
                type="string",
                description="The path of the file or empty directory to delete.",
                required=True,
            ),
        ),
    )

    def execute(self, path: str, permanent: bool = False, **kwargs: Any) -> dict[str, Any]:
        return filesystem_service.delete_file(path=path, permanent=permanent)


# Instantiated tool singletons
read_file_tool = ReadFileTool()
list_folder_tool = ListFolderTool()
create_folder_tool = CreateFolderTool()
create_file_tool = CreateFileTool()
copy_file_tool = CopyFileTool()
rename_file_tool = RenameFileTool()
move_file_tool = MoveFileTool()
delete_file_tool = DeleteFileTool()

ALL_FILESYSTEM_TOOLS = [
    read_file_tool,
    list_folder_tool,
    create_folder_tool,
    create_file_tool,
    copy_file_tool,
    rename_file_tool,
    move_file_tool,
    delete_file_tool,
]
