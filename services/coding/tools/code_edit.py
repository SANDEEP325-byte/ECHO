"""ECHO Code Modification Tool (Phase 7B).

Provides targeted block replacement with exact match verification, unified diff
generation, offline Python AST syntax pre-validation, atomic file staging,
and integration with ECHO's human confirmation boundary.
"""

from __future__ import annotations

from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.coding.diff_engine import (
    BlockAmbiguousError,
    BlockNotFoundError,
    DiffEngineError,
    SyntaxValidationError,
    diff_engine,
)
from services.coding.workspace import WorkspaceError, workspace_manager
from services.logging.logger import logger  # type: ignore[attr-defined]


class ModifyCodeTool(Tool):
    """Tool to perform targeted block replacement in workspace files."""

    name = "modify_code"
    description = (
        "Safely modifies code within an authorized workspace file by replacing a unique, "
        "exact target block with a replacement block. Generates a unified diff, performs "
        "Python AST syntax pre-validation, and writes atomically."
    )

    definition = ToolDefinition(
        name="modify_code",
        description="Replaces a unique target block in a workspace file with replacement content.",
        parameters=(
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to the file relative to the workspace root.",
                required=True,
            ),
            ToolParameter(
                name="target_block",
                type="string",
                description="Exact block of existing text to find and replace (must match uniquely).",
                required=True,
            ),
            ToolParameter(
                name="replacement_block",
                type="string",
                description="New content to replace the target block with.",
                required=True,
            ),
            ToolParameter(
                name="preview_only",
                type="boolean",
                description="If true, only returns the diff and syntax check without modifying file (default: false).",
                required=False,
            ),
        ),
    )

    def execute(  # type: ignore[override]
        self,
        file_path: str,
        target_block: str,
        replacement_block: str,
        preview_only: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute targeted code block modification."""
        if not file_path:
            return {
                "success": False,
                "error": "file_path cannot be empty.",
            }
        if not target_block:
            return {
                "success": False,
                "error": "target_block cannot be empty.",
            }

        try:
            target = workspace_manager.validate_path(
                file_path, must_exist=True, allow_sensitive=False
            )

            if not target.is_file():
                return {
                    "success": False,
                    "error": f"Target '{file_path}' is not a file.",
                }

            workspace_root = workspace_manager.root
            rel_path = target.relative_to(workspace_root).as_posix()

            # Read original content
            try:
                original_content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return {
                    "success": False,
                    "error": f"Cannot modify non-UTF8 or binary file '{file_path}'.",
                }

            # 1. Perform targeted block replacement
            try:
                modified_content = diff_engine.replace_block(
                    original_content, target_block, replacement_block
                )
            except BlockNotFoundError as exc:
                return {
                    "success": False,
                    "error": f"Block replacement failed: {exc}",
                }
            except BlockAmbiguousError as exc:
                return {
                    "success": False,
                    "error": f"Block replacement failed: {exc}",
                }
            except DiffEngineError as exc:
                return {
                    "success": False,
                    "error": f"Block replacement error: {exc}",
                }

            # 2. Generate unified diff
            diff_preview = diff_engine.generate_diff(
                original_content, modified_content, filename=rel_path
            )

            # 3. Offline AST syntax pre-validation (for Python)
            syntax_res = diff_engine.validate_python_syntax(modified_content, filename=target.name)
            if not syntax_res.valid:
                return {
                    "success": False,
                    "error": f"Syntax pre-validation failed: {syntax_res.error_message}",
                    "diff": diff_preview,
                    "syntax_status": syntax_res.status,
                }

            # 4. Preview only mode
            if preview_only:
                return {
                    "success": True,
                    "preview_only": True,
                    "file_path": rel_path,
                    "diff": diff_preview,
                    "syntax_status": syntax_res.status,
                }

            # 5. Atomic write with fail-closed guarantee
            diff_engine.atomic_write_file(target, modified_content, validate_syntax=True)

            # 6. Verification
            written_content = target.read_text(encoding="utf-8")
            if written_content != modified_content:
                return {
                    "success": False,
                    "error": "File verification failed after atomic write: content mismatch.",
                    "diff": diff_preview,
                }

            return {
                "success": True,
                "file_path": rel_path,
                "diff": diff_preview,
                "syntax_status": syntax_res.status,
            }

        except WorkspaceError as exc:
            return {
                "success": False,
                "error": f"Workspace security violation: {exc.reason}",
            }
        except SyntaxValidationError as exc:
            return {
                "success": False,
                "error": str(exc),
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": f"File not found: '{file_path}'.",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to modify code in %s: %s", file_path, exc)
            return {
                "success": False,
                "error": f"Modification failed: {exc}",
            }


modify_code_tool = ModifyCodeTool()
