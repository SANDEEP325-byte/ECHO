"""ECHO Code Tree Inspection Tool (Phase 7A).

Provides bounded, deterministic repository tree traversal that respects
workspace containment, .gitignore rules, and sensitive directory shielding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.coding.workspace import WorkspaceError, workspace_manager
from services.logging.logger import logger  # type: ignore[attr-defined]


class InspectCodeTreeTool(Tool):
    """Tool to inspect directory structure within the authorized coding workspace."""

    name = "inspect_code_tree"
    description = (
        "Inspects repository directory structure within the authorized coding workspace. "
        "Deterministically ignores .git, build artifacts, venvs, and .gitignore patterns."
    )

    definition = ToolDefinition(
        name="inspect_code_tree",
        description="Inspects directory structure within the authorized coding workspace.",
        parameters=(
            ToolParameter(
                name="path",
                type="string",
                description="Subdirectory path relative to workspace root (defaults to '.').",
                required=False,
            ),
            ToolParameter(
                name="max_depth",
                type="integer",
                description="Maximum directory recursion depth (default: 4, max: 10).",
                required=False,
            ),
            ToolParameter(
                name="max_entries",
                type="integer",
                description="Maximum total entries to return (default: 500, max: 2000).",
                required=False,
            ),
            ToolParameter(
                name="include_hidden",
                type="boolean",
                description="Whether to include non-sensitive dotfiles (default: false).",
                required=False,
            ),
        ),
    )

    def execute(
        self,
        path: str = ".",
        max_depth: int = 4,
        max_entries: int = 500,
        include_hidden: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute workspace directory tree inspection."""
        try:
            target_dir = workspace_manager.validate_path(path, must_exist=True)
            if not target_dir.is_dir():
                return {
                    "success": False,
                    "error": f"Target path '{path}' is not a directory.",
                }

            depth_limit = max(1, min(int(max_depth), 10))
            entry_limit = max(1, min(int(max_entries), 2000))
            workspace_root = workspace_manager.root

            entries: list[dict[str, Any]] = []
            truncated = False

            def _traverse(current_dir: Path, current_depth: int) -> None:
                nonlocal truncated
                if current_depth > depth_limit or len(entries) >= entry_limit:
                    if len(entries) >= entry_limit:
                        truncated = True
                    return

                try:
                    # Deterministic alphabetical sort
                    dir_items = sorted(
                        current_dir.iterdir(),
                        key=lambda p: (not p.is_dir(), p.name.lower()),
                    )
                except (PermissionError, OSError) as exc:
                    logger.warning("Skipping unreadable directory %s: %s", current_dir, exc)
                    return

                for item in dir_items:
                    if len(entries) >= entry_limit:
                        truncated = True
                        return

                    is_dir = item.is_dir()

                    # 1. Skip hidden files/dirs if not requested
                    if not include_hidden and item.name.startswith("."):
                        continue

                    # 2. Check gitignore and hardcoded exclusions
                    if workspace_manager.is_ignored(item, is_dir=is_dir):
                        continue

                    # 3. Validate item path through workspace policy to check sensitive files/dirs
                    try:
                        validated_item = workspace_manager.validate_path(
                            item, must_exist=True, allow_sensitive=False
                        )
                    except WorkspaceError:
                        # Skip sensitive files or directories silently without breaking tree
                        continue

                    rel_path = validated_item.relative_to(workspace_root).as_posix()
                    size_bytes: int | None = None
                    if not is_dir:
                        try:
                            size_bytes = validated_item.stat().st_size
                        except OSError:
                            size_bytes = None

                    entries.append(
                        {
                            "path": rel_path,
                            "type": "directory" if is_dir else "file",
                            "size_bytes": size_bytes,
                        }
                    )

                    if is_dir:
                        _traverse(validated_item, current_depth + 1)

            _traverse(target_dir, current_depth=1)

            rel_target = target_dir.relative_to(workspace_root).as_posix()
            return {
                "success": True,
                "workspace_root": str(workspace_root),
                "target_path": rel_target if rel_target else ".",
                "entries": entries,
                "total_entries": len(entries),
                "truncated": truncated,
            }

        except WorkspaceError as exc:
            return {
                "success": False,
                "error": f"Workspace security violation: {exc.reason}",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to inspect code tree for %s: %s", path, exc)
            return {
                "success": False,
                "error": f"Failed to inspect directory tree: {exc}",
            }


inspect_code_tree_tool = InspectCodeTreeTool()
