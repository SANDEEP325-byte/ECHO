"""ECHO Code Search Tool (Phase 7A).

Provides bounded, deterministic code and text searching across authorized
workspace files, supporting exact and regex matching, file pattern filtering,
and strict binary/sensitive file exclusion.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.coding.workspace import WorkspaceError, workspace_manager
from services.logging.logger import logger  # type: ignore[attr-defined]


class SearchCodeTool(Tool):
    """Tool to search code and text files within the authorized coding workspace."""

    name = "search_code"
    description = (
        "Searches for text or regex patterns in files within the authorized coding workspace. "
        "Respects .gitignore, ignores binary and sensitive files, and returns bounded snippets."
    )

    definition = ToolDefinition(
        name="search_code",
        description="Searches for text or regex patterns within the authorized coding workspace.",
        parameters=(
            ToolParameter(
                name="query",
                type="string",
                description="The search string or regular expression pattern.",
                required=True,
            ),
            ToolParameter(
                name="path",
                type="string",
                description="Subdirectory or file to search within (defaults to '.').",
                required=False,
            ),
            ToolParameter(
                name="is_regex",
                type="boolean",
                description="Whether query is a regular expression (default: false).",
                required=False,
            ),
            ToolParameter(
                name="file_pattern",
                type="string",
                description="Optional glob pattern to filter files (e.g. '*.py' or '*.ts').",
                required=False,
            ),
            ToolParameter(
                name="max_results",
                type="integer",
                description="Maximum number of matching lines to return (default: 50, max: 200).",
                required=False,
            ),
            ToolParameter(
                name="case_sensitive",
                type="boolean",
                description="Whether search is case-sensitive (default: true).",
                required=False,
            ),
        ),
    )

    def _is_binary_file(self, file_path: Path) -> bool:
        """Check if file appears to be binary by inspecting initial chunk."""
        try:
            with file_path.open("rb") as f:
                chunk = f.read(1024)
                return b"\x00" in chunk
        except OSError:
            return True

    def execute(  # type: ignore[override]
        self,
        query: str,
        path: str = ".",
        is_regex: bool = False,
        file_pattern: str | None = None,
        max_results: int = 50,
        case_sensitive: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute bounded search within workspace."""
        if not query:
            return {
                "success": False,
                "error": "Search query cannot be empty.",
            }

        try:
            target_path = workspace_manager.validate_path(path, must_exist=True)
            result_limit = max(1, min(int(max_results), 200))
            workspace_root = workspace_manager.root

            flags = 0 if case_sensitive else re.IGNORECASE
            if is_regex:
                try:
                    compiled_re = re.compile(query, flags)
                except re.error as exc:
                    return {
                        "success": False,
                        "error": f"Invalid regular expression '{query}': {exc}",
                    }
            else:
                compiled_re = re.compile(re.escape(query), flags)

            # Parse file pattern filter
            patterns: list[str] = []
            if file_pattern:
                patterns = [p.strip() for p in file_pattern.split(",") if p.strip()]

            matches: list[dict[str, Any]] = []
            truncated = False

            # Collect candidate files
            candidate_files: list[Path] = []
            if target_path.is_file():
                candidate_files.append(target_path)
            else:
                for root_dir, dirs, files in target_path.walk():
                    # Filter out ignored directories in place
                    dirs[:] = [
                        d
                        for d in dirs
                        if not workspace_manager.is_ignored(root_dir / d, is_dir=True)
                    ]

                    for fname in files:
                        file_candidate = root_dir / fname
                        if workspace_manager.is_ignored(file_candidate, is_dir=False):
                            continue

                        # Pattern filter
                        if patterns and not any(fnmatch(fname, pat) for pat in patterns):
                            continue

                        # Check sensitive files
                        try:
                            valid_f = workspace_manager.validate_path(
                                file_candidate, must_exist=True, allow_sensitive=False
                            )
                            candidate_files.append(valid_f)
                        except WorkspaceError:
                            continue

            # Sort candidate files deterministically
            candidate_files.sort()

            # Search within files
            for file_path in candidate_files:
                if len(matches) >= result_limit:
                    truncated = True
                    break

                if self._is_binary_file(file_path):
                    continue

                try:
                    rel_file = file_path.relative_to(workspace_root).as_posix()
                    with file_path.open("r", encoding="utf-8", errors="replace") as f:
                        for line_idx, line in enumerate(f, start=1):
                            if compiled_re.search(line):
                                clean_line = line.rstrip("\r\n")
                                if len(clean_line) > 200:
                                    clean_line = clean_line[:200] + "..."

                                matches.append(
                                    {
                                        "file": rel_file,
                                        "line_number": line_idx,
                                        "line_content": clean_line,
                                    }
                                )

                                if len(matches) >= result_limit:
                                    truncated = True
                                    break
                except (OSError, UnicodeDecodeError) as exc:
                    logger.warning("Error reading file %s during search: %s", file_path, exc)
                    continue

            return {
                "success": True,
                "query": query,
                "is_regex": is_regex,
                "matches": matches,
                "total_matches": len(matches),
                "truncated": truncated,
            }

        except WorkspaceError as exc:
            return {
                "success": False,
                "error": f"Workspace security violation: {exc.reason}",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to search code for %s: %s", query, exc)
            return {
                "success": False,
                "error": f"Search failed: {exc}",
            }


search_code_tool = SearchCodeTool()
