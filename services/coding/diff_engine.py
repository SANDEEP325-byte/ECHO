"""Deterministic Code Modification and Diff Engine (Phase 7B).

Provides safe targeted block replacement, unified diff generation,
deterministic patch application, offline Python AST syntax pre-validation,
and atomic file modification with fail-closed error handling.
"""

from __future__ import annotations

import ast
import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from services.logging.logger import logger  # type: ignore[attr-defined]


class DiffEngineError(Exception):
    """Base exception for code modification and diff engine failures."""


class BlockNotFoundError(DiffEngineError):
    """Raised when the target block to replace is not found in the target content."""


class BlockAmbiguousError(DiffEngineError):
    """Raised when the target block matches more than once in the target content."""


class PatchApplicationError(DiffEngineError):
    """Raised when a patch cannot be cleanly applied to the target content."""


class SyntaxValidationError(DiffEngineError):
    """Raised when Python AST syntax pre-validation fails."""


@dataclass(frozen=True)
class SyntaxValidationResult:
    """Result of offline syntax validation."""

    valid: bool
    status: str  # "VALID", "INVALID", "NOT_APPLICABLE"
    error_message: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass
class PatchHunk:
    """Represents a parsed unified diff hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


class DiffEngine:
    """Deterministic diff generation, patch application, and code modification engine."""

    HUNK_HEADER_REGEX = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")

    def replace_block(
        self,
        original_content: str,
        target_block: str,
        replacement_block: str,
    ) -> str:
        """Safely replace a target block with a replacement block.

        Guarantees:
        - Fails closed with BlockNotFoundError if target_block is not found.
        - Fails closed with BlockAmbiguousError if target_block matches multiple times.
        - Preserves exact whitespace and unmodified code.
        """
        if not target_block:
            raise DiffEngineError("Target block to replace cannot be empty.")

        count = original_content.count(target_block)
        if count == 0:
            # Check for possible CRLF / LF line ending mismatch to provide helpful diagnostics
            normalized_orig = original_content.replace("\r\n", "\n")
            normalized_target = target_block.replace("\r\n", "\n")
            if normalized_orig.count(normalized_target) > 0:
                raise BlockNotFoundError(
                    "Target block not found due to newline mismatch (CRLF vs LF). "
                    "Ensure matching line endings."
                )
            raise BlockNotFoundError("Target block was not found in the file content.")

        if count > 1:
            raise BlockAmbiguousError(
                f"Target block matches {count} locations in the file. "
                "The target block must match exactly one location to prevent ambiguous edits."
            )

        return original_content.replace(target_block, replacement_block, 1)

    def generate_diff(
        self,
        original_content: str,
        modified_content: str,
        filename: str = "file",
        context_lines: int = 3,
        max_diff_chars: int = 16000,
    ) -> str:
        """Generate a deterministic, bounded unified diff preview."""
        orig_lines = original_content.splitlines(keepends=True)
        mod_lines = modified_content.splitlines(keepends=True)

        norm_filename = filename.replace("\\", "/")
        diff_lines = list(
            difflib.unified_diff(
                orig_lines,
                mod_lines,
                fromfile=f"a/{norm_filename}",
                tofile=f"b/{norm_filename}",
                n=context_lines,
            )
        )

        diff_text = "".join(diff_lines)
        if len(diff_text) > max_diff_chars:
            diff_text = (
                diff_text[:max_diff_chars]
                + f"\n... [diff truncated: limit of {max_diff_chars} characters reached]"
            )

        return diff_text

    def validate_python_syntax(
        self,
        content: str,
        filename: str = "script.py",
    ) -> SyntaxValidationResult:
        """Perform offline AST syntax pre-validation on Python code without executing it.

        Returns NOT_APPLICABLE for non-Python files.
        """
        suffix = Path(filename).suffix.lower()
        if suffix not in (".py", ".pyw"):
            return SyntaxValidationResult(
                valid=True,
                status="NOT_APPLICABLE",
                error_message=None,
            )

        try:
            ast.parse(content, filename=filename)
            return SyntaxValidationResult(
                valid=True,
                status="VALID",
                error_message=None,
            )
        except SyntaxError as exc:
            return SyntaxValidationResult(
                valid=False,
                status="INVALID",
                error_message=f"SyntaxError: {exc.msg} at line {exc.lineno}, col {exc.offset}",
                line=exc.lineno,
                column=exc.offset,
            )
        except Exception as exc:  # noqa: BLE001
            return SyntaxValidationResult(
                valid=False,
                status="INVALID",
                error_message=f"Parsing error: {exc}",
            )

    def parse_unified_patch(self, patch_str: str) -> list[PatchHunk]:
        """Parse a unified diff into structured PatchHunk objects."""
        lines = patch_str.splitlines()
        hunks: list[PatchHunk] = []
        current_hunk: PatchHunk | None = None

        for line in lines:
            match = self.HUNK_HEADER_REGEX.match(line)
            if match:
                if current_hunk is not None:
                    hunks.append(current_hunk)

                old_start = int(match.group(1))
                old_count = int(match.group(2)) if match.group(2) is not None else 1
                new_start = int(match.group(3))
                new_count = int(match.group(4)) if match.group(4) is not None else 1

                current_hunk = PatchHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=[],
                )
            elif current_hunk is not None:
                if line.startswith(("+", "-", " ", "\\")):
                    current_hunk.lines.append(line)

        if current_hunk is not None:
            hunks.append(current_hunk)

        if not hunks:
            raise PatchApplicationError(
                "No valid unified diff hunks (@@ -start,count +start,count @@) found in patch."
            )

        return hunks

    def apply_unified_patch(
        self,
        original_content: str,
        patch_str: str,
    ) -> str:
        """Apply a unified diff patch to original content deterministically.

        Validates context lines and line positions. Fails closed if context does not match.
        """
        hunks = self.parse_unified_patch(patch_str)
        orig_lines = original_content.splitlines()
        has_trailing_newline = original_content.endswith(("\n", "\r\n"))

        result: list[str] = []
        current_line_idx = 0  # 0-indexed in orig_lines

        for hunk in hunks:
            hunk_target_idx = hunk.old_start - 1 if hunk.old_start > 0 else 0

            # Copy unchanged lines up to the hunk start
            if current_line_idx < hunk_target_idx:
                result.extend(orig_lines[current_line_idx:hunk_target_idx])
                current_line_idx = hunk_target_idx

            hunk_orig_idx = current_line_idx
            for hline in hunk.lines:
                if not hline:
                    continue
                indicator = hline[0]
                text = hline[1:]

                if indicator == " ":
                    # Context line: must match original
                    if hunk_orig_idx >= len(orig_lines):
                        raise PatchApplicationError(
                            f"Hunk context beyond end of file at line {hunk_orig_idx + 1}."
                        )
                    if orig_lines[hunk_orig_idx] != text:
                        raise PatchApplicationError(
                            f"Hunk context mismatch at line {hunk_orig_idx + 1}. "
                            f"Expected: '{text}', Found: '{orig_lines[hunk_orig_idx]}'."
                        )
                    result.append(text)
                    hunk_orig_idx += 1
                elif indicator == "-":
                    # Deleted line: must match original
                    if hunk_orig_idx >= len(orig_lines):
                        raise PatchApplicationError(
                            f"Hunk delete target beyond end of file at line {hunk_orig_idx + 1}."
                        )
                    if orig_lines[hunk_orig_idx] != text:
                        raise PatchApplicationError(
                            f"Hunk delete mismatch at line {hunk_orig_idx + 1}. "
                            f"Expected: '{text}', Found: '{orig_lines[hunk_orig_idx]}'."
                        )
                    hunk_orig_idx += 1
                elif indicator == "+":
                    # Added line
                    result.append(text)
                elif indicator == "\\":
                    # e.g., \ No newline at end of file
                    continue
                else:
                    raise PatchApplicationError(f"Unexpected patch line indicator: '{indicator}'")

            current_line_idx = hunk_orig_idx

        # Append remaining lines after last hunk
        if current_line_idx < len(orig_lines):
            result.extend(orig_lines[current_line_idx:])

        # Determine appropriate newline convention
        newline = "\r\n" if "\r\n" in original_content else "\n"
        output = newline.join(result)
        if has_trailing_newline and not output.endswith(newline):
            output += newline

        return output

    def atomic_write_file(
        self,
        target_path: Path,
        new_content: str,
        validate_syntax: bool = True,
    ) -> SyntaxValidationResult:
        """Write new content to target_path atomically and fail-closed.

        Guarantees:
        1. Pre-validates syntax for Python files using AST parse. Fails closed if invalid.
        2. Writes to a temporary file in the target directory.
        3. Atomically replaces target_path.
        4. Cleans up temporary staging file deterministically in all cases.
        """
        syntax_res = SyntaxValidationResult(valid=True, status="NOT_APPLICABLE")
        if validate_syntax:
            syntax_res = self.validate_python_syntax(new_content, filename=target_path.name)
            if not syntax_res.valid:
                raise SyntaxValidationError(
                    f"Syntax pre-validation failed for '{target_path.name}': {syntax_res.error_message}"
                )

        target_dir = target_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        temp_file = None
        try:
            # Create temp file in the same directory to ensure atomic os.replace on the same filesystem
            temp_name = f".{target_path.name}.tmp.{uuid4().hex[:8]}"
            temp_file_path = target_dir / temp_name
            temp_file = temp_file_path

            # Detect encoding or default to utf-8
            temp_file_path.write_text(new_content, encoding="utf-8")

            # Atomically replace target
            os.replace(temp_file_path, target_path)
            temp_file = None  # Replaced successfully
            return syntax_res
        finally:
            if temp_file is not None and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to clean up staging file %s: %s", temp_file, exc)


# Singleton instance
diff_engine = DiffEngine()
