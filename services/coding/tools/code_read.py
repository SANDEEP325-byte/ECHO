"""ECHO Code Read Tool (Phase 7A).

Provides line-bounded, deterministic file reading within the authorized coding
workspace, preventing unbounded whole-repository reads, memory exhaustion,
and binary/sensitive file exposure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.coding.workspace import WorkspaceError, workspace_manager
from services.logging.logger import logger  # type: ignore[attr-defined]


class ReadCodeTool(Tool):
    """Tool to read line-bounded portions of source files within the authorized workspace."""

    name = "read_code"
    description = (
        "Reads a line-bounded section of a source code or text file within the authorized workspace. "
        "Enforces line limits, maximum output size, and shields sensitive or binary files."
    )

    definition = ToolDefinition(
        name="read_code",
        description="Reads a bounded line range from a file within the authorized workspace.",
        parameters=(
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to the file relative to the workspace root.",
                required=True,
            ),
            ToolParameter(
                name="start_line",
                type="integer",
                description="Starting line number, 1-indexed (default: 1).",
                required=False,
            ),
            ToolParameter(
                name="end_line",
                type="integer",
                description="Ending line number, 1-indexed inclusive (optional).",
                required=False,
            ),
            ToolParameter(
                name="max_lines",
                type="integer",
                description="Maximum number of lines to return (default: 200, max: 1000).",
                required=False,
            ),
        ),
    )

    MAX_BYTES_BOUND = 65536  # 64 KB max content size per call

    def _is_binary(self, file_path: Path) -> bool:
        """Check if file contains null bytes in initial chunk."""
        try:
            with file_path.open("rb") as f:
                chunk = f.read(1024)
                return b"\x00" in chunk
        except OSError:
            return True

    def execute(  # type: ignore[override]
        self,
        file_path: str,
        start_line: int = 1,
        end_line: int | None = None,
        max_lines: int = 200,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute line-bounded file read."""
        if not file_path:
            return {
                "success": False,
                "error": "file_path cannot be empty.",
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

            if self._is_binary(target):
                return {
                    "success": False,
                    "error": f"Cannot read binary file '{file_path}'.",
                }

            start = max(1, int(start_line))
            line_cap = max(1, min(int(max_lines), 1000))
            if end_line is not None:
                requested_end = max(start, int(end_line))
                limit_end = min(requested_end, start + line_cap - 1)
            else:
                limit_end = start + line_cap - 1

            workspace_root = workspace_manager.root
            rel_path = target.relative_to(workspace_root).as_posix()

            lines: list[str] = []
            total_file_lines = 0
            eof_reached = False
            bytes_read = 0
            truncated_bytes = False

            with target.open("r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f, start=1):
                    total_file_lines = idx
                    if start <= idx <= limit_end:
                        line_bytes = len(line.encode("utf-8", errors="replace"))
                        if bytes_read + line_bytes > self.MAX_BYTES_BOUND:
                            truncated_bytes = True
                            break
                        bytes_read += line_bytes
                        lines.append(line)
                    elif idx > limit_end:
                        break

            # If we exited loop before limit_end without hitting byte cap, we reached EOF
            if total_file_lines <= limit_end and not truncated_bytes:
                eof_reached = True

            actual_end = start + len(lines) - 1 if lines else start - 1
            content = "".join(lines)

            return {
                "operation": "read_code",
                "success": True,
                "file_path": rel_path,
                "start_line": start,
                "end_line": actual_end,
                "total_lines_read": len(lines),
                "total_file_lines": total_file_lines,
                "content": content,
                "eof": eof_reached,
                "truncated": truncated_bytes
                or (actual_end < (end_line or limit_end) and not eof_reached),
            }

        except WorkspaceError as exc:
            return {
                "operation": "read_code",
                "success": False,
                "error": f"Workspace security violation: {exc.reason}",
            }
        except FileNotFoundError:
            return {
                "operation": "read_code",
                "success": False,
                "error": f"File not found: '{file_path}'.",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to read code from %s: %s", file_path, exc)
            return {
                "operation": "read_code",
                "success": False,
                "error": f"Read failed: {exc}",
            }


read_code_tool = ReadCodeTool()
