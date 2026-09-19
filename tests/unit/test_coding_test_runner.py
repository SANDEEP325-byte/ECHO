"""Unit tests for ECHO Controlled Test Execution & Command Hardening (Phase 7C).

Tests cover:
- TestFilterValidator (safe grammar for -k and -m, rejection of dangerous constructs)
- TestExecutionPolicy (target resolution, node selector parsing, argument allowlisting, env sanitization)
- TestRunner execution with mocked subprocess (success, failure, timeout, truncation, parsing)
- RunTestsTool and ToolRegistry integration
- SafetyEngine and RiskClassifier classification (RiskLevel.SENSITIVE, PermissionDecision.CONFIRM)
- ExecutionEngine confirmation workflow and PendingAction generation
- VerificationEngine postcondition mapping (VERIFIED, NOT_VERIFIED, VERIFICATION_ERROR)
- ResponseGenerator safe confirmation prompt generation
"""

import subprocess
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.common.tool_registry import tool_registry
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request
from packages.interfaces.security import PermissionDecision, RiskLevel
from packages.interfaces.verification import VerificationStatus
from services.brain.execution import ExecutionEngine
from services.brain.response_generator import response_generator
from services.brain.verification import VerificationEngine
from services.coding.test_runner import (
    TestExecutionPolicy,
    TestFilterValidator,
    TestFramework,
    TestPolicyError,
    TestResult,
    TestRunner,
    TestSummary,
)
from services.coding.tools.test_runner import RunTestsTool, run_tests_tool
from services.coding.workspace import workspace_manager
from services.security.risk import risk_classifier
from services.security.safety_engine import SafetyEngine


@pytest.fixture
def test_workspace(tmp_path: Path) -> Generator[Path, None, None]:
    """Configure an isolated temporary workspace for tests."""
    old_root = workspace_manager.root
    workspace_manager.set_root(tmp_path)
    # Create test directory and test file for valid targets
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / "test_example.py"
    test_file.write_text("def test_one(): pass\n", encoding="utf-8")

    yield tmp_path
    workspace_manager.set_root(old_root)


# =========================================================================
# 1. TestFilterValidator: -k and -m Expression Grammar Tests
# =========================================================================


class TestTestFilterValidator:
    """Tests for safe conservative grammar on pytest -k and -m expressions."""

    def test_valid_simple_identifiers(self) -> None:
        assert TestFilterValidator.validate("unit") == "unit"
        assert TestFilterValidator.validate("test_method_1") == "test_method_1"
        assert TestFilterValidator.validate("FeatureFlag") == "FeatureFlag"

    def test_valid_quoted_literals(self) -> None:
        assert TestFilterValidator.validate("'test_feature'") == "'test_feature'"
        assert TestFilterValidator.validate('"test_feature"') == '"test_feature"'

    def test_valid_boolean_operators(self) -> None:
        expr = "unit and not slow"
        assert TestFilterValidator.validate(expr) == expr

        expr2 = "fast or smoke or (integration and not heavy)"
        assert TestFilterValidator.validate(expr2) == expr2

    def test_valid_parentheses_nesting(self) -> None:
        expr = "((unit and fast) or (smoke and not slow))"
        assert TestFilterValidator.validate(expr) == expr

    def test_reject_excessive_nesting_depth(self) -> None:
        # Nesting depth > 3 must be rejected
        deep_expr = "((((unit))))"
        with pytest.raises(TestPolicyError, match="exceeds maximum depth"):
            TestFilterValidator.validate(deep_expr)

    def test_reject_unbalanced_parentheses(self) -> None:
        with pytest.raises(TestPolicyError, match="Unmatched"):
            TestFilterValidator.validate("(unit and slow")
        with pytest.raises(TestPolicyError, match="Unmatched"):
            TestFilterValidator.validate("unit and slow)")

    def test_reject_function_calls_and_builtins(self) -> None:
        with pytest.raises(TestPolicyError):
            TestFilterValidator.validate("__import__('os').system('calc')")
        with pytest.raises(TestPolicyError):
            TestFilterValidator.validate("eval('1+1')")

    def test_reject_attribute_access(self) -> None:
        with pytest.raises(TestPolicyError):
            TestFilterValidator.validate("os.path.exists")
        with pytest.raises(TestPolicyError):
            TestFilterValidator.validate("foo.bar")

    def test_reject_shell_metacharacters(self) -> None:
        dangerous = [
            "unit; rm -rf /",
            "unit && calc",
            "unit | cat",
            "unit `whoami`",
            "unit $(whoami)",
            "unit > out.txt",
            "unit < in.txt",
            "unit \n rm",
        ]
        for expr in dangerous:
            with pytest.raises(TestPolicyError):
                TestFilterValidator.validate(expr)

    def test_reject_excessive_length(self) -> None:
        long_expr = "a" * 105
        with pytest.raises(TestPolicyError, match="exceeds maximum allowed length"):
            TestFilterValidator.validate(long_expr)

    def test_reject_empty_or_whitespace(self) -> None:
        with pytest.raises(TestPolicyError):
            TestFilterValidator.validate("")
        with pytest.raises(TestPolicyError):
            TestFilterValidator.validate("   ")


# =========================================================================
# 2. TestExecutionPolicy: Target Validation and Option Allowlisting Tests
# =========================================================================


class TestTestExecutionPolicy:
    """Tests for target path validation and argument allowlisting."""

    def test_validate_pytest_full_suite(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        cmd = policy.build_command(TestFramework.PYTEST, targets=None, options=None)
        assert len(cmd) >= 2
        assert "pytest" in cmd[1] or "pytest" in cmd[2]

    def test_validate_pytest_directory_target(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        cmd = policy.build_command(TestFramework.PYTEST, targets=["tests"])
        assert any("tests" in arg for arg in cmd)

    def test_validate_pytest_file_target(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        cmd = policy.build_command(TestFramework.PYTEST, targets=["tests/test_example.py"])
        assert any("test_example.py" in arg for arg in cmd)

    def test_validate_pytest_node_selector(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        cmd = policy.build_command(
            TestFramework.PYTEST,
            targets=["tests/test_example.py::TestClass::test_method"],
        )
        assert any("::TestClass::test_method" in arg for arg in cmd)

    def test_validate_pytest_invalid_node_syntax(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        with pytest.raises(TestPolicyError, match="Invalid test node"):
            policy.build_command(
                TestFramework.PYTEST,
                targets=["tests/test_example.py:::bad_syntax"],
            )

    def test_validate_unittest_module_target(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        cmd = policy.build_command(
            TestFramework.UNITTEST,
            targets=["tests.test_example"],
        )
        assert "-m" in cmd
        assert "unittest" in cmd
        assert "tests.test_example" in cmd

    def test_validate_unittest_rejects_arbitrary_module(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        # unittest framework only invokes `python -m unittest`
        cmd = policy.build_command(TestFramework.UNITTEST, targets=["tests/test_example.py"])
        assert "unittest" in cmd
        assert not any(arg in cmd for arg in ["subprocess", "os", "sys"])

    def test_validate_unittest_rejects_non_unittest_options(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        with pytest.raises(TestPolicyError, match="not permitted for unittest"):
            policy.build_command(
                TestFramework.UNITTEST,
                targets=["tests.test_example"],
                options=["--tb=short"],
            )

    def test_allowlisted_pytest_options(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        options = [
            "-v",
            "-vv",
            "-q",
            "-x",
            "--tb=short",
            "--maxfail=3",
            "--durations=5",
            "-k",
            "unit and not slow",
            "-m",
            "fast",
        ]
        cmd = policy.build_command(TestFramework.PYTEST, targets=None, options=options)
        for opt in ["-v", "-vv", "-q", "-x", "--tb=short", "--maxfail=3", "--durations=5"]:
            assert opt in cmd
        assert "-k" in cmd
        assert "unit and not slow" in cmd
        assert "-m" in cmd
        assert "fast" in cmd

    def test_reject_forbidden_options(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        forbidden_options = [
            "--rootdir=/tmp",
            "-c",
            "custom.ini",
            "--config-file=custom.ini",
            "-o",
            "cache_dir=/tmp",
            "--override-ini=cache_dir=/tmp",
            "--confcutdir=/tmp",
            "-p",
            "pytest_benchmark",
            "--pdb",
            "--trace",
            "--capture=no",
            "-n",
            "auto",
            "--arbitrary-flag",
        ]
        for opt in forbidden_options:
            with pytest.raises(TestPolicyError, match="not in the approved positive allowlist"):
                policy.build_command(TestFramework.PYTEST, targets=None, options=[opt])

    def test_reject_traversal_target(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        with pytest.raises(TestPolicyError):
            policy.build_command(TestFramework.PYTEST, targets=["../../outside.py"])

    def test_reject_unc_target(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        with pytest.raises(TestPolicyError):
            policy.build_command(TestFramework.PYTEST, targets=["//server/share/test.py"])

    def test_reject_sensitive_targets(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        sensitive_targets = [
            ".env",
            ".git",
            ".git/config",
            "id_rsa",
            "credentials.json",
        ]
        for target in sensitive_targets:
            with pytest.raises(TestPolicyError):
                policy.build_command(TestFramework.PYTEST, targets=[target])

    def test_reject_excessive_targets(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        many_targets = [f"tests/test_{i}.py" for i in range(55)]
        with pytest.raises(TestPolicyError, match="Too many target paths"):
            policy.build_command(TestFramework.PYTEST, targets=many_targets)

    def test_reject_excessive_options(self, test_workspace: Path) -> None:
        policy = TestExecutionPolicy()
        many_options = ["-v"] * 25
        with pytest.raises(TestPolicyError, match="Too many test options"):
            policy.build_command(TestFramework.PYTEST, targets=None, options=many_options)


# =========================================================================
# 3. Environment Sanitization Tests
# =========================================================================


class TestEnvironmentSanitization:
    """Tests to verify environment sanitization removes secrets and injection vectors."""

    def test_sanitized_env_scrubs_secrets_and_injection(self) -> None:
        policy = TestExecutionPolicy()
        tainted_env = {
            "PATH": "C:\\Windows;C:\\Python",
            "PYTHONPATH": "C:\\malicious\\lib",
            "PYTHONSTARTUP": "C:\\malicious\\startup.py",
            "GIT_DIR": "C:\\repo\\.git",
            "GIT_WORK_TREE": "C:\\repo",
            "AWS_SECRET_ACCESS_KEY": "super_secret_key",
            "OPENAI_API_KEY": "sk-1234567890",
            "DB_PASSWORD": "secret_password",
            "SAFE_VAR": "regular_value",
        }
        with patch.dict("os.environ", tainted_env, clear=True):
            clean_env = policy.build_sanitized_env()

            # Sensitive variables removed
            assert "AWS_SECRET_ACCESS_KEY" not in clean_env
            assert "OPENAI_API_KEY" not in clean_env
            assert "DB_PASSWORD" not in clean_env

            # Python injection variables removed
            assert "PYTHONPATH" not in clean_env
            assert "PYTHONSTARTUP" not in clean_env

            # Git injection variables removed
            assert "GIT_DIR" not in clean_env
            assert "GIT_WORK_TREE" not in clean_env

            # Safe variables preserved
            assert clean_env.get("SAFE_VAR") == "regular_value"
            assert "PATH" in clean_env
            assert clean_env.get("PYTHONDONTWRITEBYTECODE") == "1"


# =========================================================================
# 4. TestRunner Execution & Result Parsing Tests (Mocked Subprocess)
# =========================================================================


class TestTestRunnerExecution:
    """Tests for TestRunner execution lifecycle with mocked subprocesses."""

    @patch("subprocess.run")
    def test_run_pytest_success(self, mock_run: MagicMock, test_workspace: Path) -> None:
        runner = TestRunner()
        mock_output = (
            "============================= test session starts =============================\n"
            "tests/test_example.py .                                                  [100%]\n"
            "============================== 5 passed in 0.25s ==============================\n"
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=["pytest"],
            returncode=0,
            stdout=mock_output,
            stderr="",
        )

        result = runner.run_tests(framework="pytest")
        assert result.success is True
        assert result.exit_code == 0
        assert result.status == "passed"
        assert result.summary.passed == 5
        assert result.summary.failed == 0
        assert result.timed_out is False
        assert result.truncated is False
        assert result.to_dict()["operation"] == "run_tests"

    @patch("subprocess.run")
    def test_run_pytest_failure(self, mock_run: MagicMock, test_workspace: Path) -> None:
        runner = TestRunner()
        mock_output = (
            "============================= test session starts =============================\n"
            "FAILURES:\n"
            "_________________________________ test_fail __________________________________\n"
            "def test_fail():\n"
            ">       assert 1 == 2\n"
            "E       assert 1 == 2\n"
            "tests/test_example.py:5: AssertionError\n"
            "========================= 1 failed, 2 passed in 0.30s =========================\n"
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=["pytest"],
            returncode=1,
            stdout=mock_output,
            stderr="",
        )

        result = runner.run_tests(framework="pytest")
        assert result.success is False
        assert result.exit_code == 1
        assert result.status == "failed"
        assert result.summary.failed == 1
        assert result.summary.passed == 2
        assert len(result.failures) >= 1
        assert result.failures[0]["name"] == "test_fail"

    @patch("subprocess.run")
    def test_run_pytest_no_tests_collected(self, mock_run: MagicMock, test_workspace: Path) -> None:
        runner = TestRunner()
        mock_run.return_value = subprocess.CompletedProcess(
            args=["pytest"],
            returncode=5,
            stdout="collected 0 items\n===== no tests ran in 0.01s =====",
            stderr="",
        )

        result = runner.run_tests(framework="pytest")
        assert result.success is False
        assert result.exit_code == 5
        assert result.status == "no_tests_collected"

    @patch("subprocess.run")
    def test_run_pytest_timeout(self, mock_run: MagicMock, test_workspace: Path) -> None:
        runner = TestRunner()
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["pytest"],
            timeout=10.0,
            output=b"Running tests...",
            stderr=b"",
        )

        result = runner.run_tests(framework="pytest", timeout=10.0)
        assert result.success is False
        assert result.timed_out is True
        assert result.status == "timeout"
        assert "timed out" in result.stderr.lower()

    @patch("subprocess.run")
    def test_run_output_truncation(self, mock_run: MagicMock, test_workspace: Path) -> None:
        runner = TestRunner()
        huge_stdout = "x" * 70000  # 70 KB > 64 KB limit
        mock_run.return_value = subprocess.CompletedProcess(
            args=["pytest"],
            returncode=0,
            stdout=huge_stdout,
            stderr="",
        )

        result = runner.run_tests(framework="pytest")
        assert result.truncated is True
        assert len(result.stdout) <= 65536
        assert "TRUNCATED" in result.stdout

    @patch("subprocess.run")
    def test_run_process_error(self, mock_run: MagicMock, test_workspace: Path) -> None:
        runner = TestRunner()
        mock_run.side_effect = OSError("Subprocess launch failed")

        result = runner.run_tests(framework="pytest")
        assert result.success is False
        assert result.status == "error"
        assert result.exit_code is None
        assert "Subprocess launch failed" in result.stderr

    @patch("subprocess.run")
    def test_run_unittest_success(self, mock_run: MagicMock, test_workspace: Path) -> None:
        runner = TestRunner()
        mock_stderr = (
            "...\n"
            "----------------------------------------------------------------------\n"
            "Ran 3 tests in 0.050s\n\n"
            "OK\n"
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=["python", "-m", "unittest"],
            returncode=0,
            stdout="",
            stderr=mock_stderr,
        )

        result = runner.run_tests(framework="unittest", targets=["tests.test_example"])
        assert result.success is True
        assert result.status == "passed"
        assert result.summary.passed == 3
        assert result.summary.total == 3


# =========================================================================
# 5. RunTestsTool & Tool Registration Tests
# =========================================================================


class TestRunTestsTool:
    """Tests for RunTestsTool interface and tool registration."""

    def test_tool_definition_and_parameters(self) -> None:
        assert run_tests_tool.name == "run_tests"
        param_names = [p.name for p in run_tests_tool.definition.parameters]
        assert "framework" in param_names
        assert "targets" in param_names
        assert "options" in param_names
        assert "timeout" in param_names

    def test_tool_registered_in_registry(self) -> None:
        tool = tool_registry.get("run_tests")
        assert tool is not None
        assert tool.name == "run_tests"

    @patch("services.coding.test_runner.TestRunner.run_tests")
    def test_tool_execute_success(self, mock_run_tests: MagicMock, test_workspace: Path) -> None:
        mock_run_tests.return_value = TestResult(
            success=True,
            framework="pytest",
            command="pytest",
            exit_code=0,
            status="passed",
            summary=TestSummary(passed=2, total=2),
        )

        tool = RunTestsTool()
        result = tool.execute(framework="pytest")
        assert result["success"] is True
        assert result["operation"] == "run_tests"
        assert result["status"] == "passed"

    def test_tool_execute_policy_violation(self, test_workspace: Path) -> None:
        tool = RunTestsTool()
        result = tool.execute(options=["--rootdir=/etc"])
        assert result["success"] is False
        assert result["status"] == "error"
        assert "policy violation" in result["error"].lower()
        assert result["operation"] == "run_tests"


# =========================================================================
# 6. SafetyEngine & Confirmation Boundary Tests
# =========================================================================


class TestSafetyAndConfirmation:
    """Tests for RiskClassifier, SafetyEngine, and ExecutionEngine confirmation."""

    def test_risk_classification_is_sensitive(self) -> None:
        risk = risk_classifier.classify("run_tests")
        assert risk == RiskLevel.SENSITIVE

    def test_safety_engine_decision_is_confirm(self) -> None:
        safety_engine = SafetyEngine()
        result = safety_engine.evaluate("run_tests")
        assert result.decision == PermissionDecision.CONFIRM
        assert result.risk_level == RiskLevel.SENSITIVE
        assert "confirmation is required" in result.reason.lower()

    def test_execution_engine_requires_confirmation(self, test_workspace: Path) -> None:
        engine = ExecutionEngine()
        plan = Plan(
            requires_planning=True,
            steps=[
                PlanStep(
                    step_number=1,
                    description="Run test suite",
                    tool_name="run_tests",
                    arguments={"framework": "pytest"},
                )
            ],
        )
        request = Request(user_input="run tests")
        request.selected_tools = ["run_tests"]
        exec_result = engine.execute(request, plan)

        assert exec_result.requires_confirmation is True
        assert exec_result.pending_action is not None
        assert exec_result.pending_action["tool"] == "run_tests"
        assert exec_result.pending_action["risk_level"] == "sensitive"

    def test_safe_confirmation_prompt_formatting(self) -> None:
        pending_action = {
            "tool": "run_tests",
            "arguments": {
                "framework": "pytest",
                "targets": ["tests/test_example.py"],
                "timeout": 20.0,
            },
        }
        prompt = response_generator.generate_confirmation_prompt(pending_action)
        assert "pytest" in prompt
        assert "tests/test_example.py" in prompt
        assert "20.0s" in prompt
        assert "Would you like to proceed? (yes/no)" in prompt
        # Must not expose raw dicts or secret variables
        assert "{" not in prompt
        assert "api_key" not in prompt.lower()


# =========================================================================
# 7. VerificationEngine Integration Tests
# =========================================================================


class TestVerificationEngineIntegration:
    """Tests for VerificationEngine postcondition verification of test results."""

    def test_verification_status_verified_on_success(self) -> None:
        engine = VerificationEngine()
        test_meta = {
            "operation": "run_tests",
            "success": True,
            "exit_code": 0,
            "status": "passed",
            "summary": {"passed": 10, "failed": 0, "total": 10},
        }
        detail = engine._verify_operation_postcondition(test_meta)
        assert detail.status == VerificationStatus.VERIFIED
        assert "passed successfully" in detail.message.lower()

    def test_verification_status_not_verified_on_failure(self) -> None:
        engine = VerificationEngine()
        test_meta = {
            "operation": "run_tests",
            "success": False,
            "exit_code": 1,
            "status": "failed",
            "summary": {"passed": 8, "failed": 2, "total": 10},
        }
        detail = engine._verify_operation_postcondition(test_meta)
        assert detail.status == VerificationStatus.NOT_VERIFIED
        assert "failed" in detail.message.lower()

    def test_verification_status_not_verified_on_timeout(self) -> None:
        engine = VerificationEngine()
        test_meta = {
            "operation": "run_tests",
            "success": False,
            "exit_code": None,
            "status": "timeout",
            "timed_out": True,
        }
        detail = engine._verify_operation_postcondition(test_meta)
        assert detail.status == VerificationStatus.NOT_VERIFIED
        assert "timed out" in detail.message.lower()

    def test_verification_status_not_verified_on_no_tests(self) -> None:
        engine = VerificationEngine()
        test_meta = {
            "operation": "run_tests",
            "success": False,
            "exit_code": 5,
            "status": "no_tests_collected",
        }
        detail = engine._verify_operation_postcondition(test_meta)
        assert detail.status == VerificationStatus.NOT_VERIFIED
        assert "no tests were collected" in detail.message.lower()

    def test_verification_status_error_on_process_error(self) -> None:
        engine = VerificationEngine()
        test_meta = {
            "operation": "run_tests",
            "success": False,
            "exit_code": None,
            "status": "error",
            "error": "Subprocess execution failed",
        }
        detail = engine._verify_operation_postcondition(test_meta)
        assert detail.status == VerificationStatus.VERIFICATION_ERROR
        assert "error" in detail.message.lower()

    def test_verification_status_error_on_framework_exit_code(self) -> None:
        engine = VerificationEngine()
        # pytest exit code 2: command-line usage error or interrupted
        test_meta = {
            "operation": "run_tests",
            "success": False,
            "exit_code": 2,
            "status": "error",
        }
        detail = engine._verify_operation_postcondition(test_meta)
        assert detail.status == VerificationStatus.VERIFICATION_ERROR
