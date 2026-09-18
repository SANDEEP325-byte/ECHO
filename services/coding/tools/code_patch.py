"""ECHO Patch Application Tool (Phase 7B).

Provides deterministic unified diff patch validation and application with
hunk context verification, path traversal checks, Python AST syntax pre-validation,
and atomic file staging.
"""

from __future__ import annotations

from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.coding.diff_engine import (
    PatchApplicationError,
    SyntaxValidationError,
    diff_engine,
)
from services.coding.workspace import WorkspaceError, workspace_manager
from services.logging.logger import logger  # type: ignore[attr-defined]


class ApplyPatchTool(Tool):
    """Tool to apply unified diff patches to workspace files."""

    name = "apply_patch"
    description = (
        "Applies a validated unified diff patch to an authorized workspace file. "
        "Enforces context matching, rejects path traversal, validates syntax, and writes atomically."
    )

    definition = ToolDefinition(
        name="apply_patch",
        description="Applies a unified diff patch to a workspace file.",
        parameters=(
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to the file relative to the workspace root.",
                required=True,
            ),
            ToolParameter(
                name="patch",
                type="string",
                description="Unified diff patch content (containing @@ hunks).",
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

    def _validate_patch_headers(self, patch: str, expected_filename: str) -> None:
        """Ensure patch header paths do not attempt directory traversal or UNC escapes."""
        for line in patch.splitlines():
            if line.startswith(("--- ", "+++ ")):
                header_target = line[4:].strip()
                # Strip typical unified diff prefixes a/ and b/
                if header_target.startswith(("a/", "b/")):
                    header_target = header_target[2:]

                if (
                    ".." in header_target
                    or "\x00" in header_target
                    or header_target.startswith(("\\\\", "//"))
                ):
                    raise PatchApplicationError(
                        f"Prohibited path traversal or network path in patch header: '{header_target}'"
                    )

    def execute(  # type: ignore[override]
        self,
        file_path: str,
        patch: str,
        preview_only: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute unified patch application."""
        if not file_path:
            return {
                "success": False,
                "error": "file_path cannot be empty.",
            }
        if not patch:
            return {
                "success": False,
                "error": "patch content cannot be empty.",
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

            # 1. Validate patch headers against path traversal
            try:
                self._validate_patch_headers(patch, target.name)
            except PatchApplicationError as exc:
                return {
                    "success": False,
                    "error": str(exc),
                }

            # 2. Read original content
            try:
                original_content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return {
                    "success": False,
                    "error": f"Cannot patch non-UTF8 or binary file '{file_path}'.",
                }

            # 3. Apply patch deterministically
            try:
                modified_content = diff_engine.apply_unified_patch(original_content, patch)
            except PatchApplicationError as exc:
                return {
                    "success": False,
                    "error": f"Patch application failed: {exc}",
                }

            # 4. Generate clean diff preview
            diff_preview = diff_engine.generate_diff(
                original_content, modified_content, filename=rel_path
            )

            # 5. Offline AST syntax pre-validation (for Python)
            syntax_res = diff_engine.validate_python_syntax(modified_content, filename=target.name)
            if not syntax_res.valid:
                return {
                    "success": False,
                    "error": f"Syntax pre-validation failed: {syntax_res.error_message}",
                    "diff": diff_preview,
                    "syntax_status": syntax_res.status,
                }

            # 6. Preview only mode
            if preview_only:
                return {
                    "success": True,
                    "preview_only": True,
                    "file_path": rel_path,
                    "diff": diff_preview,
                    "syntax_status": syntax_res.status,
                }

            # 7. Atomic write with fail-closed guarantee
            diff_engine.atomic_write_file(target, modified_content, validate_syntax=True)

            # 8. Verification
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
            logger.error("Failed to apply patch to %s: %s", file_path, exc)
            return {
                "success": False,
                "error": f"Patch failed: {exc}",
            }


apply_patch_tool = ApplyPatchTool()
