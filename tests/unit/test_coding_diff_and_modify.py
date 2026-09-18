"""Unit tests for ECHO Diff Engine and Code Modification Tools (Phase 7B).

Tests for:
- DiffEngine (replace_block, generate_diff, validate_python_syntax, apply_unified_patch, atomic_write_file)
- ModifyCodeTool (modify_code)
- ApplyPatchTool (apply_patch)
- Safety confirmation boundary integration with SafetyEngine and ExecutionEngine
"""

from collections.abc import Generator
from pathlib import Path

import pytest

from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request
from packages.interfaces.security import PermissionDecision, RiskLevel
from services.brain.execution import ExecutionEngine
from services.coding.diff_engine import (
    BlockAmbiguousError,
    BlockNotFoundError,
    PatchApplicationError,
    SyntaxValidationError,
    diff_engine,
)
from services.coding.tools.code_edit import ModifyCodeTool
from services.coding.tools.code_patch import ApplyPatchTool
from services.coding.workspace import workspace_manager
from services.security.risk import risk_classifier
from services.security.safety_engine import SafetyEngine


@pytest.fixture
def test_workspace(tmp_path: Path) -> Generator[Path, None, None]:
    """Fixture that configures an isolated temporary workspace for tests."""
    old_root = workspace_manager.root
    workspace_manager.set_root(tmp_path)
    yield tmp_path
    workspace_manager.set_root(old_root)


class TestDiffEngine:
    """Tests for core DiffEngine capabilities."""

    def test_replace_block_exact(self) -> None:
        original = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        target = "def foo():\n    return 1"
        replacement = "def foo():\n    return 42"

        result = diff_engine.replace_block(original, target, replacement)
        assert "return 42" in result
        assert "def bar():\n    return 2" in result

    def test_replace_block_not_found(self) -> None:
        original = "def foo():\n    return 1\n"
        with pytest.raises(BlockNotFoundError):
            diff_engine.replace_block(original, "def missing(): pass", "replacement")

    def test_replace_block_ambiguous_multiple_matches(self) -> None:
        original = "value = 10\nvalue = 10\n"
        with pytest.raises(BlockAmbiguousError) as exc_info:
            diff_engine.replace_block(original, "value = 10", "value = 20")
        assert "matches 2 locations" in str(exc_info.value)

    def test_generate_diff_bounded(self) -> None:
        original = "line 1\nline 2\nline 3\n"
        modified = "line 1\nline TWO\nline 3\n"
        diff = diff_engine.generate_diff(original, modified, filename="example.txt")

        assert "--- a/example.txt" in diff
        assert "+++ b/example.txt" in diff
        assert "-line 2" in diff
        assert "+line TWO" in diff

        # Test bounded character limit
        long_orig = "\n".join(f"orig_{i}" for i in range(500))
        long_mod = "\n".join(f"mod_{i}" for i in range(500))
        bounded_diff = diff_engine.generate_diff(
            long_orig, long_mod, filename="big.txt", max_diff_chars=100
        )
        assert len(bounded_diff) <= 200
        assert "diff truncated" in bounded_diff

    def test_validate_python_syntax_valid_and_invalid(self) -> None:
        valid_py = "def hello() -> str:\n    return 'world'\n"
        res_valid = diff_engine.validate_python_syntax(valid_py, "hello.py")
        assert res_valid.valid is True
        assert res_valid.status == "VALID"

        invalid_py = "def broken(:\n    return\n"
        res_invalid = diff_engine.validate_python_syntax(invalid_py, "broken.py")
        assert res_invalid.valid is False
        assert res_invalid.status == "INVALID"
        assert res_invalid.line == 1
        assert "SyntaxError" in (res_invalid.error_message or "")

    def test_validate_syntax_non_python_not_applicable(self) -> None:
        json_content = '{"key": "value"}'
        res = diff_engine.validate_python_syntax(json_content, "data.json")
        assert res.valid is True
        assert res.status == "NOT_APPLICABLE"

    def test_apply_unified_patch_success(self) -> None:
        original = "alpha\nbeta\ngamma\n"
        patch = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " alpha\n"
            "-beta\n"
            "+beta_modified\n"
            " gamma\n"
        )
        modified = diff_engine.apply_unified_patch(original, patch)
        assert modified == "alpha\nbeta_modified\ngamma\n"

    def test_apply_unified_patch_context_mismatch_fails_closed(self) -> None:
        original = "alpha\nbeta\ngamma\n"
        patch = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " wrong_context\n"
            "-beta\n"
            "+beta_modified\n"
            " gamma\n"
        )
        with pytest.raises(PatchApplicationError) as exc_info:
            diff_engine.apply_unified_patch(original, patch)
        assert "mismatch at line 1" in str(exc_info.value)

    def test_atomic_write_file_syntax_rollback(self, tmp_path: Path) -> None:
        target_py = tmp_path / "code.py"
        original_code = "def valid():\n    return True\n"
        target_py.write_text(original_code, encoding="utf-8")

        broken_code = "def broken(:\n    return False\n"
        with pytest.raises(SyntaxValidationError):
            diff_engine.atomic_write_file(target_py, broken_code, validate_syntax=True)

        # File must remain completely unchanged
        assert target_py.read_text(encoding="utf-8") == original_code


class TestModifyCodeTool:
    """Tests for ModifyCodeTool."""

    def test_modify_code_success(self, test_workspace: Path) -> None:
        tool = ModifyCodeTool()
        target = test_workspace / "math.py"
        target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

        res = tool.execute(
            file_path="math.py",
            target_block="return a - b",
            replacement_block="return a + b",
        )
        assert res["success"] is True
        assert res["syntax_status"] == "VALID"
        assert "+    return a + b" in res["diff"]
        assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"

    def test_modify_code_preview_only(self, test_workspace: Path) -> None:
        tool = ModifyCodeTool()
        target = test_workspace / "test.py"
        initial_content = "x = 1\n"
        target.write_text(initial_content, encoding="utf-8")

        res = tool.execute(
            file_path="test.py",
            target_block="x = 1",
            replacement_block="x = 2",
            preview_only=True,
        )
        assert res["success"] is True
        assert res["preview_only"] is True
        assert "+x = 2" in res["diff"]
        # Target file on disk must NOT be modified
        assert target.read_text(encoding="utf-8") == initial_content

    def test_modify_code_syntax_failure_rejection(self, test_workspace: Path) -> None:
        tool = ModifyCodeTool()
        target = test_workspace / "script.py"
        initial_content = "def run():\n    pass\n"
        target.write_text(initial_content, encoding="utf-8")

        res = tool.execute(
            file_path="script.py",
            target_block="pass",
            replacement_block="broken(def",
        )
        assert res["success"] is False
        assert "Syntax pre-validation failed" in res["error"]
        assert target.read_text(encoding="utf-8") == initial_content

    def test_modify_code_sensitive_file_rejected(self, test_workspace: Path) -> None:
        tool = ModifyCodeTool()
        target = test_workspace / ".env"
        target.write_text("SECRET=1\n", encoding="utf-8")

        res = tool.execute(
            file_path=".env",
            target_block="SECRET=1",
            replacement_block="SECRET=2",
        )
        assert res["success"] is False
        assert "Workspace security violation" in res["error"]


class TestApplyPatchTool:
    """Tests for ApplyPatchTool."""

    def test_apply_patch_success(self, test_workspace: Path) -> None:
        tool = ApplyPatchTool()
        target = test_workspace / "app.py"
        target.write_text("print('start')\nprint('old')\nprint('end')\n", encoding="utf-8")

        patch = (
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1,3 +1,3 @@\n"
            " print('start')\n"
            "-print('old')\n"
            "+print('new')\n"
            " print('end')\n"
        )
        res = tool.execute(file_path="app.py", patch=patch)
        assert res["success"] is True
        assert target.read_text(encoding="utf-8") == (
            "print('start')\nprint('new')\nprint('end')\n"
        )

    def test_apply_patch_header_traversal_rejected(self, test_workspace: Path) -> None:
        tool = ApplyPatchTool()
        target = test_workspace / "app.py"
        target.write_text("print('test')\n", encoding="utf-8")

        malicious_patch = (
            "--- a/../secret.txt\n"
            "+++ b/../secret.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-print('test')\n"
            "+print('hacked')\n"
        )
        res = tool.execute(file_path="app.py", patch=malicious_patch)
        assert res["success"] is False
        assert "path traversal" in res["error"].lower()


class TestCodingSafetyConfirmationBoundary:
    """Tests verifying that coding modifications require human confirmation via ECHO SafetyEngine."""

    def test_risk_classification(self) -> None:
        assert risk_classifier.classify("inspect_code_tree") == RiskLevel.SAFE
        assert risk_classifier.classify("search_code") == RiskLevel.SAFE
        assert risk_classifier.classify("read_code") == RiskLevel.SAFE
        assert risk_classifier.classify("modify_code") == RiskLevel.SENSITIVE
        assert risk_classifier.classify("apply_patch") == RiskLevel.SENSITIVE

    def test_safety_engine_evaluation(self) -> None:
        engine = SafetyEngine()
        assert engine.evaluate("inspect_code_tree").decision == PermissionDecision.ALLOW
        assert engine.evaluate("search_code").decision == PermissionDecision.ALLOW
        assert engine.evaluate("read_code").decision == PermissionDecision.ALLOW
        assert engine.evaluate("modify_code").decision == PermissionDecision.CONFIRM
        assert engine.evaluate("apply_patch").decision == PermissionDecision.CONFIRM

    def test_execution_engine_creates_pending_action_for_modify_code(
        self, test_workspace: Path
    ) -> None:
        exec_engine = ExecutionEngine()
        req = Request(
            user_input="Change add function to plus",
            selected_tools=["modify_code"],
        )
        plan = Plan(
            requires_planning=True,
            steps=[
                PlanStep(
                    step_number=1,
                    description="Modify math.py",
                    tool_name="modify_code",
                    arguments={
                        "file_path": "math.py",
                        "target_block": "return a - b",
                        "replacement_block": "return a + b",
                    },
                )
            ],
        )

        result = exec_engine.execute(req, plan)
        assert result.success is False
        assert result.requires_confirmation is True
        assert result.pending_action is not None
        assert result.pending_action["tool"] == "modify_code"
        assert result.pending_action["risk_level"] == RiskLevel.SENSITIVE.value
