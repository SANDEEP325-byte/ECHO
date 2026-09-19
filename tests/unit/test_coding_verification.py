"""Unit tests for ECHO Phase 7F: Coding Verification & Regression Protection.

Verifies:
- Passive postcondition verification for modify_code.
- Passive postcondition verification for apply_patch.
- Detection of invalid Python syntax (VERIFICATION_ERROR).
- Rejection of out-of-workspace targets (VERIFICATION_ERROR).
- Rejection of empty/missing diff evidence (NOT_VERIFIED).
- Preview-only verification without disk mutation (VERIFIED).
- Read-only coding tools classified as NOT_APPLICABLE.
- run_tests verification behavior (passed, failed, timeout, no tests, process error).
- Verification is strictly passive (no double execution or silent mutation).
- Multi-step workflow verification behavior.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from packages.interfaces.execution import ExecutionResult
from packages.interfaces.request import Request
from packages.interfaces.verification import VerificationStatus
from services.brain.verification import VerificationEngine
from services.coding.workspace import workspace_manager


class TestCodingVerification:
    """Postcondition verification test suite for coding tools."""

    def setup_method(self) -> None:
        self.old_root = workspace_manager.root
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        workspace_manager.set_root(self.root)
        self.engine = VerificationEngine()

        # Create sample files
        self.valid_py = self.root / "module.py"
        self.valid_py.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

        self.valid_txt = self.root / "notes.txt"
        self.valid_txt.write_text("Sample notes\n", encoding="utf-8")

    def teardown_method(self) -> None:
        if hasattr(self, "old_root") and self.old_root and self.old_root.exists():
            workspace_manager.set_root(self.old_root)
        else:
            workspace_manager.set_root(Path.cwd())
        self.temp_dir.cleanup()

    # -----------------------------------------------------------------------
    # 1. modify_code Verification Tests
    # -----------------------------------------------------------------------

    def test_verify_modify_code_success(self) -> None:
        """Verify successful modify_code postcondition with valid syntax and diff."""
        req = Request(user_input="Modify module.py")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "modify_code",
                "success": True,
                "file_path": "module.py",
                "target_path": "module.py",
                "diff": "--- a/module.py\n+++ b/module.py\n@@ -1,2 +1,2 @@\n-return 'world'\n+return 'echo'\n",
                "syntax_status": "valid",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is True
        assert res.status == VerificationStatus.VERIFIED
        assert res.details is not None
        assert len(res.details) == 1
        assert res.details[0].status == VerificationStatus.VERIFIED
        assert "module.py" in res.details[0].message

    def test_verify_modify_code_invalid_syntax(self) -> None:
        """Verify modify_code fails with VERIFICATION_ERROR when syntax_status is invalid."""
        req = Request(user_input="Modify module.py with bad syntax")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "modify_code",
                "success": True,
                "file_path": "module.py",
                "target_path": "module.py",
                "diff": "@@ -1 +1 @@\n+def broken(:",
                "syntax_status": "invalid",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.VERIFICATION_ERROR
        assert res.error is not None
        assert "syntax" in res.error.lower()

    def test_verify_modify_code_out_of_workspace_escape(self) -> None:
        """Verify modify_code returns VERIFICATION_ERROR when target attempts workspace escape."""
        req = Request(user_input="Escape workspace")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "modify_code",
                "success": True,
                "file_path": "../../system_file.py",
                "target_path": "../../system_file.py",
                "diff": "@@ -1 +1 @@",
                "syntax_status": "valid",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.VERIFICATION_ERROR
        assert res.error is not None
        assert "workspace policy" in res.error.lower()

    def test_verify_modify_code_missing_diff_evidence(self) -> None:
        """Verify modify_code fails postcondition when diff is empty or missing."""
        req = Request(user_input="Modify module.py")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "modify_code",
                "success": True,
                "file_path": "module.py",
                "target_path": "module.py",
                "diff": "",
                "syntax_status": "valid",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.NOT_VERIFIED
        assert res.error is not None
        assert "diff" in res.error.lower()

    def test_verify_modify_code_preview_only_no_mutation(self) -> None:
        """Verify preview_only mode verifies successfully without expecting disk write."""
        req = Request(user_input="Preview changes to module.py")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "modify_code",
                "success": True,
                "preview_only": True,
                "file_path": "module.py",
                "target_path": "module.py",
                "diff": "--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@",
                "syntax_status": "valid",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is True
        assert res.status == VerificationStatus.VERIFIED
        assert res.details is not None
        assert "preview" in res.details[0].message.lower()

    def test_verify_modify_code_operation_failure(self) -> None:
        """Verify modify_code returns NOT_VERIFIED if the operation itself reported failure."""
        req = Request(user_input="Modify missing file")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "modify_code",
                "success": False,
                "error": "Target 'missing.py' is not a file.",
                "target_path": "missing.py",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.NOT_VERIFIED

    # -----------------------------------------------------------------------
    # 2. apply_patch Verification Tests
    # -----------------------------------------------------------------------

    def test_verify_apply_patch_success(self) -> None:
        """Verify apply_patch postcondition succeeds on valid modification."""
        req = Request(user_input="Apply patch to notes.txt")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "apply_patch",
                "success": True,
                "file_path": "notes.txt",
                "target_path": "notes.txt",
                "diff": "--- a/notes.txt\n+++ b/notes.txt\n@@ -1 +1 @@\n-Sample notes\n+Updated notes\n",
                "syntax_status": "skipped",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is True
        assert res.status == VerificationStatus.VERIFIED

    def test_verify_apply_patch_missing_metadata(self) -> None:
        """Verify apply_patch returns VERIFICATION_ERROR when target_path is missing."""
        req = Request(user_input="Apply patch without target")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "apply_patch",
                "success": True,
                "diff": "@@ diff @@",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.VERIFICATION_ERROR

    # -----------------------------------------------------------------------
    # 3. Read-Only Tools Verification (NOT_APPLICABLE)
    # -----------------------------------------------------------------------

    def test_verify_read_only_coding_tools_not_applicable(self) -> None:
        """Verify read_code, search_code, and inspect_code_tree evaluate to NOT_APPLICABLE."""
        req = Request(user_input="Read and search code")
        exec_res = ExecutionResult(
            success=True,
            result=[
                {"operation": "read_code", "success": True, "file_path": "module.py"},
                {"operation": "search_code", "success": True, "query": "hello"},
                {
                    "operation": "inspect_code_tree",
                    "success": True,
                    "workspace_root": str(self.root),
                },
            ],
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is True
        assert res.status == VerificationStatus.NOT_APPLICABLE
        assert res.details is not None
        assert len(res.details) == 3
        for detail in res.details:
            assert detail.status == VerificationStatus.NOT_APPLICABLE

    # -----------------------------------------------------------------------
    # 4. run_tests Verification Behavior
    # -----------------------------------------------------------------------

    def test_verify_run_tests_passed(self) -> None:
        """Verify run_tests exit_code 0 is VERIFIED."""
        req = Request(user_input="Run tests")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "run_tests",
                "success": True,
                "exit_code": 0,
                "status": "passed",
                "summary": {"passed": 5, "failed": 0},
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is True
        assert res.status == VerificationStatus.VERIFIED

    def test_verify_run_tests_failed(self) -> None:
        """Verify run_tests with failures returns NOT_VERIFIED."""
        req = Request(user_input="Run tests")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "run_tests",
                "success": False,
                "exit_code": 1,
                "status": "failed",
                "summary": {"passed": 4, "failed": 1},
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.NOT_VERIFIED

    def test_verify_run_tests_timeout(self) -> None:
        """Verify timed out run_tests returns NOT_VERIFIED."""
        req = Request(user_input="Run slow tests")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "run_tests",
                "success": False,
                "timed_out": True,
                "status": "timeout",
                "exit_code": None,
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.NOT_VERIFIED

    def test_verify_run_tests_process_error(self) -> None:
        """Verify internal runner error returns VERIFICATION_ERROR."""
        req = Request(user_input="Run broken runner")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "run_tests",
                "success": False,
                "status": "error",
                "exit_code": None,
                "error": "Failed to spawn pytest process",
            },
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.VERIFICATION_ERROR

    # -----------------------------------------------------------------------
    # 5. Multi-Step Workflow & Passive Verification Invariant
    # -----------------------------------------------------------------------

    def test_multi_step_workflow_fails_if_tests_fail_after_modify(self) -> None:
        """Verify that a multi-step workflow evaluates to NOT_VERIFIED if tests fail after modify."""
        req = Request(user_input="Read, modify, and test")
        exec_res = ExecutionResult(
            success=True,
            result=[
                {"operation": "read_code", "success": True, "file_path": "module.py"},
                {
                    "operation": "modify_code",
                    "success": True,
                    "file_path": "module.py",
                    "target_path": "module.py",
                    "diff": "@@ -1 +1 @@",
                    "syntax_status": "valid",
                },
                {
                    "operation": "run_tests",
                    "success": False,
                    "exit_code": 1,
                    "status": "failed",
                    "summary": {"passed": 0, "failed": 1},
                },
            ],
        )
        res = self.engine.verify(req, exec_res)
        assert res.success is False
        assert res.status == VerificationStatus.NOT_VERIFIED
        assert res.details is not None
        assert len(res.details) == 3
        assert res.details[0].status == VerificationStatus.NOT_APPLICABLE
        assert res.details[1].status == VerificationStatus.VERIFIED
        assert res.details[2].status == VerificationStatus.NOT_VERIFIED

    def test_verification_is_strictly_passive_no_subprocesses(self) -> None:
        """Verify VerificationEngine does not mutate disk state or execute commands."""
        initial_content = self.valid_py.read_text(encoding="utf-8")
        req = Request(user_input="Verify modification")
        exec_res = ExecutionResult(
            success=True,
            result={
                "operation": "modify_code",
                "success": True,
                "file_path": "module.py",
                "target_path": "module.py",
                "diff": "@@ -1 +1 @@",
                "syntax_status": "valid",
            },
        )
        # Verify runs purely passively
        res = self.engine.verify(req, exec_res)
        assert res.success is True
        # Content on disk must remain exactly what was there
        assert self.valid_py.read_text(encoding="utf-8") == initial_content
