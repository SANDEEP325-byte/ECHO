"""Unit tests for ECHO Code Inspection Tools (Phase 7A).

Tests for:
- inspect_code_tree
- search_code
- read_code
"""

from collections.abc import Generator
from pathlib import Path

import pytest

from services.coding.tools.code_read import ReadCodeTool
from services.coding.tools.code_search import SearchCodeTool
from services.coding.tools.code_tree import InspectCodeTreeTool
from services.coding.workspace import workspace_manager


@pytest.fixture
def test_workspace(tmp_path: Path) -> Generator[Path, None, None]:
    """Fixture that configures an isolated temporary workspace for tests."""
    old_root = workspace_manager.root
    workspace_manager.set_root(tmp_path)
    yield tmp_path
    workspace_manager.set_root(old_root)


class TestInspectCodeTreeTool:
    """Tests for inspect_code_tree."""

    def test_tree_traversal_and_exclusions(self, test_workspace: Path) -> None:
        tool = InspectCodeTreeTool()

        # Setup directory structure
        (test_workspace / "src").mkdir()
        (test_workspace / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
        (test_workspace / "src" / "utils.py").write_text("def add(): pass", encoding="utf-8")
        (test_workspace / "docs").mkdir()
        (test_workspace / "docs" / "readme.md").write_text("# Doc", encoding="utf-8")

        # Excluded / sensitive files & dirs
        (test_workspace / ".git").mkdir()
        (test_workspace / ".git" / "config").write_text("git config", encoding="utf-8")
        (test_workspace / ".env").write_text("SECRET=1", encoding="utf-8")
        (test_workspace / "node_modules").mkdir()
        (test_workspace / "node_modules" / "package.json").write_text("{}", encoding="utf-8")

        res = tool.execute(path=".")
        assert res["success"] is True
        paths = [e["path"] for e in res["entries"]]

        assert "src" in paths
        assert "src/main.py" in paths
        assert "src/utils.py" in paths
        assert "docs/readme.md" in paths

        # Exclusions
        assert ".git" not in paths
        assert ".git/config" not in paths
        assert ".env" not in paths
        assert "node_modules" not in paths

    def test_tree_max_depth_and_entries_bounds(self, test_workspace: Path) -> None:
        tool = InspectCodeTreeTool()

        # Create nested directories
        d = test_workspace
        for i in range(6):
            d = d / f"level_{i}"
            d.mkdir()
            (d / "file.txt").write_text(f"level {i}", encoding="utf-8")

        res_depth = tool.execute(path=".", max_depth=2)
        assert res_depth["success"] is True
        for e in res_depth["entries"]:
            assert e["path"].count("/") <= 2

        res_entries = tool.execute(path=".", max_entries=3)
        assert res_entries["success"] is True
        assert len(res_entries["entries"]) <= 3
        assert res_entries["truncated"] is True

    def test_tree_workspace_escape_rejected(self, test_workspace: Path) -> None:
        tool = InspectCodeTreeTool()
        res = tool.execute(path="../outside")
        assert res["success"] is False
        assert "Workspace security violation" in res["error"]


class TestSearchCodeTool:
    """Tests for search_code."""

    def test_search_literal_and_regex(self, test_workspace: Path) -> None:
        tool = SearchCodeTool()

        (test_workspace / "src").mkdir()
        (test_workspace / "src" / "alpha.py").write_text(
            "def calculate_total(price, tax):\n    return price + tax\n", encoding="utf-8"
        )
        (test_workspace / "src" / "beta.py").write_text(
            "def calculate_discount(price):\n    return price * 0.9\n", encoding="utf-8"
        )

        # Literal search
        res = tool.execute(query="calculate_total")
        assert res["success"] is True
        assert len(res["matches"]) == 1
        assert res["matches"][0]["file"] == "src/alpha.py"
        assert res["matches"][0]["line_number"] == 1
        assert "calculate_total" in res["matches"][0]["line_content"]

        # Regex search
        res_re = tool.execute(query=r"calculate_\w+", is_regex=True)
        assert res_re["success"] is True
        assert len(res_re["matches"]) == 2

    def test_search_invalid_regex(self, test_workspace: Path) -> None:
        tool = SearchCodeTool()
        res = tool.execute(query="[unclosed_bracket", is_regex=True)
        assert res["success"] is False
        assert "Invalid regular expression" in res["error"]

    def test_search_binary_and_sensitive_files_skipped(self, test_workspace: Path) -> None:
        tool = SearchCodeTool()

        # Binary file containing target string and null byte
        (test_workspace / "image.bin").write_bytes(b"TARGET_WORD\x00\x01\x02")
        # Sensitive file
        (test_workspace / ".env").write_text("TARGET_WORD=secret", encoding="utf-8")
        # Normal code file
        (test_workspace / "code.py").write_text("print('TARGET_WORD')", encoding="utf-8")

        res = tool.execute(query="TARGET_WORD")
        assert res["success"] is True
        assert len(res["matches"]) == 1
        assert res["matches"][0]["file"] == "code.py"

    def test_search_file_pattern_filter(self, test_workspace: Path) -> None:
        tool = SearchCodeTool()
        (test_workspace / "a.py").write_text("FOUND_KEY", encoding="utf-8")
        (test_workspace / "b.txt").write_text("FOUND_KEY", encoding="utf-8")

        res = tool.execute(query="FOUND_KEY", file_pattern="*.py")
        assert res["success"] is True
        assert len(res["matches"]) == 1
        assert res["matches"][0]["file"] == "a.py"

    def test_search_bounds_and_truncation(self, test_workspace: Path) -> None:
        tool = SearchCodeTool()
        lines = "\n".join(f"MATCH_LINE {i}" for i in range(100))
        (test_workspace / "large.txt").write_text(lines, encoding="utf-8")

        res = tool.execute(query="MATCH_LINE", max_results=10)
        assert res["success"] is True
        assert len(res["matches"]) == 10
        assert res["truncated"] is True


class TestReadCodeTool:
    """Tests for read_code."""

    def test_read_line_range(self, test_workspace: Path) -> None:
        tool = ReadCodeTool()
        content = "\n".join(f"line_{i}" for i in range(1, 21))
        (test_workspace / "sample.py").write_text(content, encoding="utf-8")

        res = tool.execute(file_path="sample.py", start_line=5, end_line=10)
        assert res["success"] is True
        assert res["start_line"] == 5
        assert res["end_line"] == 10
        assert res["total_lines_read"] == 6
        assert "line_5\nline_6" in res["content"]
        assert "line_4" not in res["content"]
        assert "line_11" not in res["content"]

    def test_read_empty_file(self, test_workspace: Path) -> None:
        tool = ReadCodeTool()
        (test_workspace / "empty.py").write_text("", encoding="utf-8")
        res = tool.execute(file_path="empty.py")
        assert res["success"] is True
        assert res["content"] == ""
        assert res["total_lines_read"] == 0
        assert res["eof"] is True

    def test_read_binary_file_rejected(self, test_workspace: Path) -> None:
        tool = ReadCodeTool()
        (test_workspace / "test.bin").write_bytes(b"\x00\x01\x02\x03")
        res = tool.execute(file_path="test.bin")
        assert res["success"] is False
        assert "Cannot read binary file" in res["error"]

    def test_read_sensitive_file_rejected(self, test_workspace: Path) -> None:
        tool = ReadCodeTool()
        (test_workspace / ".env").write_text("API_KEY=12345", encoding="utf-8")
        res = tool.execute(file_path=".env")
        assert res["success"] is False
        assert "Workspace security violation" in res["error"]

    def test_read_workspace_escape_rejected(self, test_workspace: Path) -> None:
        tool = ReadCodeTool()
        res = tool.execute(file_path="../outside.py")
        assert res["success"] is False
        assert "Workspace security violation" in res["error"]
