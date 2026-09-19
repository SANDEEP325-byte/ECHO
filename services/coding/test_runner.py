"""Controlled Test Execution Engine & Command Hardening (Phase 7C).

Provides safe, deterministic, local-first test execution for pytest and unittest
within the authorized CodingWorkspace. Enforces positive argument allowlisting,
conservative filter grammar validation, workspace confinement, environment sanitization,
strict timeouts, bounded output, and structured test result parsing.

IMPORTANT SECURITY NOTICE:
Executing repository tests involves running Python code controlled by the repository.
This runner enforces strict command policy, argument allowlisting, and process controls,
but does NOT provide VM/container kernel-level sandboxing. Mandatory user confirmation
is strictly required for every test execution.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from services.coding.workspace import WorkspaceError, workspace_manager
from services.desktop.commands import (
    CommandExecutor,
    command_execution_policy,
)
from services.logging.logger import logger  # type: ignore[attr-defined]


class TestFramework(str, Enum):
    """Supported test frameworks."""

    __test__ = False
    PYTEST = "pytest"
    UNITTEST = "unittest"


class TestErrorCode(str, Enum):
    """Structured error codes for test execution failures."""

    INVALID_ARGUMENTS = "invalid_arguments"
    UNAUTHORIZED_TARGET = "unauthorized_target"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    EXECUTION_FAILED = "execution_failed"
    POLICY_BLOCKED = "policy_blocked"


class TestPolicyError(PermissionError):
    """Raised when test execution violates security policy or argument allowlists."""

    __test__ = False

    def __init__(self, reason: str, error_code: TestErrorCode) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_code = error_code


@dataclass
class TestSummary:
    """Structured summary counts for test execution."""

    __test__ = False
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    total: int = 0
    duration_seconds: float | None = None


@dataclass
class TestResult:
    """Structured result of a controlled test execution."""

    __test__ = False
    success: bool
    framework: str
    command: str
    exit_code: int | None
    status: str  # "passed", "failed", "error", "timeout", "no_tests_collected"
    summary: TestSummary = field(default_factory=TestSummary)
    failures: list[dict[str, str]] = field(default_factory=list)
    timed_out: bool = False
    truncated: bool = False
    stdout: str = ""
    stderr: str = ""
    cwd: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert result to structured dictionary representation."""
        return {
            "operation": "run_tests",
            "success": self.success,
            "framework": self.framework,
            "command": self.command,
            "exit_code": self.exit_code,
            "status": self.status,
            "summary": {
                "passed": self.summary.passed,
                "failed": self.summary.failed,
                "skipped": self.summary.skipped,
                "errors": self.summary.errors,
                "total": self.summary.total,
                "duration_seconds": self.summary.duration_seconds,
            },
            "failures": self.failures,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "cwd": self.cwd,
        }


class TestFilterValidator:
    """Conservative, deterministic validator for pytest -k and -m filter expressions.

    Accepts a strictly defined safe subset:
    - Identifiers: [a-zA-Z_][a-zA-Z0-9_]*
    - Quoted identifiers: '[a-zA-Z0-9_]+' or "[a-zA-Z0-9_]+"
    - Boolean operators: and, or, not
    - Grouping parentheses with balanced nesting depth <= 3

    Strictly rejects function calls, attribute access (.), comparisons, semicolons,
    shell characters, and excessive length.
    """

    MAX_LENGTH = 100
    MAX_NESTING_DEPTH = 3

    IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    QUOTED_PATTERN = re.compile(r"^(['\"])[a-zA-Z0-9_]+\1$")
    BOOLEAN_OPERATORS = frozenset({"and", "or", "not"})

    # Tokenizer matching identifiers, quoted strings, parentheses, or individual symbols
    TOKEN_REGEX = re.compile(
        r"['\"][a-zA-Z0-9_]+['\"]|[a-zA-Z_][a-zA-Z0-9_]*|\(|\)|[^\s\w\(\)'\"]+"
    )

    @classmethod
    def validate(cls, expr: str, option_name: str = "-k") -> str:
        """Validate filter expression against conservative grammar."""
        if not expr or not isinstance(expr, str):
            raise TestPolicyError(
                f"Filter expression for '{option_name}' must be a non-empty string.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        clean = expr.strip()
        if not clean:
            raise TestPolicyError(
                f"Filter expression for '{option_name}' cannot be blank.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        if len(clean) > cls.MAX_LENGTH:
            raise TestPolicyError(
                f"Filter expression for '{option_name}' exceeds maximum allowed length of {cls.MAX_LENGTH} characters.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        # Prohibit any characters that could imply code execution or shell metacharacters
        forbidden_chars = (
            ";",
            "&",
            "|",
            "<",
            ">",
            "`",
            "$",
            "{",
            "}",
            "[",
            "]",
            "\\",
            "/",
            ".",
            "=",
            ":",
            "*",
            "!",
            "@",
        )
        for ch in forbidden_chars:
            if ch in clean:
                raise TestPolicyError(
                    f"Forbidden character '{ch}' in '{option_name}' expression. "
                    "Only identifiers, quotes, and boolean operators (and, or, not) are permitted.",
                    TestErrorCode.INVALID_ARGUMENTS,
                )

        tokens = cls.TOKEN_REGEX.findall(clean)
        if not tokens:
            raise TestPolicyError(
                f"Invalid empty token stream for '{option_name}' expression.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        paren_depth = 0
        prev_token: str | None = None

        for token in tokens:
            # Check parentheses
            if token == "(":
                paren_depth += 1
                if paren_depth > cls.MAX_NESTING_DEPTH:
                    raise TestPolicyError(
                        f"Parentheses nesting in '{option_name}' exceeds maximum depth of {cls.MAX_NESTING_DEPTH}.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                prev_token = token
                continue
            elif token == ")":
                paren_depth -= 1
                if paren_depth < 0:
                    raise TestPolicyError(
                        f"Unmatched closing parenthesis in '{option_name}' expression.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                prev_token = token
                continue

            token_lower = token.lower()

            # Check boolean operators
            if token_lower in cls.BOOLEAN_OPERATORS:
                prev_token = token_lower
                continue

            # Check quoted identifier
            if cls.QUOTED_PATTERN.match(token):
                # Reject adjacent identifiers without operator
                if prev_token is not None and prev_token not in ("(", "and", "or", "not"):
                    raise TestPolicyError(
                        f"Missing operator between '{prev_token}' and '{token}' in '{option_name}' expression.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                prev_token = token
                continue

            # Check unquoted identifier
            if cls.IDENTIFIER_PATTERN.match(token):
                # Reject adjacent identifiers without operator
                if prev_token is not None and prev_token not in ("(", "and", "or", "not"):
                    raise TestPolicyError(
                        f"Missing operator between '{prev_token}' and '{token}' in '{option_name}' expression.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                prev_token = token
                continue

            # Unrecognized token
            raise TestPolicyError(
                f"Invalid or unsafe token '{token}' in '{option_name}' expression.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        if paren_depth != 0:
            raise TestPolicyError(
                f"Unmatched opening parenthesis in '{option_name}' expression.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        return clean


class TestExecutionPolicy:
    """Policy engine enforcing strict positive allowlisting for test execution."""

    __test__ = False

    ALLOWED_FRAMEWORKS = frozenset({TestFramework.PYTEST, TestFramework.UNITTEST})

    MAX_ARGUMENTS = 20
    MAX_TARGETS = 5
    DEFAULT_TIMEOUT = 30.0
    MIN_TIMEOUT = 1.0
    MAX_TIMEOUT = 60.0
    DEFAULT_MAX_OUTPUT_BYTES = 65536  # 64 KB

    # Positive allowlist of safe standalone flags
    ALLOWED_BOOLEAN_FLAGS = frozenset({"-v", "-vv", "-q", "-x"})

    # Positive allowlist of safe options with arguments
    ALLOWED_OPTION_PREFIXES = frozenset(
        {
            "--tb=",
            "--maxfail=",
            "--durations=",
        }
    )

    ALLOWED_TB_VALUES = frozenset({"short", "line", "auto", "no"})

    def __init__(self) -> None:
        self.filter_validator = TestFilterValidator()

    def resolve_python_executable(self) -> Path:
        """Resolve trusted Python executable."""
        try:
            return command_execution_policy.resolve_executable("python")
        except Exception:  # noqa: BLE001
            # Fallback to sys.base_prefix if standard policy resolution is customized
            base_py = Path(sys.base_prefix) / "python.exe"
            if base_py.exists():
                return base_py
            return Path(sys.executable)

    def validate_target(self, target: str) -> str:
        """Validate target test path or node within authorized workspace.

        Supports:
        - Directory path: tests/unit/
        - File path: tests/unit/test_sample.py
        - Node selector: tests/unit/test_sample.py::TestClass::test_method
        - Module format for unittest: tests.test_sample
        """
        if not target or not isinstance(target, str):
            raise TestPolicyError(
                "Target test path cannot be empty.", TestErrorCode.INVALID_ARGUMENTS
            )

        clean_target = target.strip()
        if not clean_target:
            raise TestPolicyError(
                "Target test path cannot be blank.", TestErrorCode.INVALID_ARGUMENTS
            )

        # Separate file path from node selector if present
        if "::" in clean_target:
            parts = clean_target.split("::")
            file_part = parts[0]
            node_parts = parts[1:]

            for node in node_parts:
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", node):
                    raise TestPolicyError(
                        f"Invalid test node identifier '{node}'. Only valid Python identifiers are permitted.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )

            if not file_part.endswith(".py"):
                raise TestPolicyError(
                    f"Target file in node selector '{clean_target}' must be a Python (.py) file.",
                    TestErrorCode.INVALID_ARGUMENTS,
                )

            try:
                valid_path = workspace_manager.validate_path(
                    file_part, must_exist=True, allow_sensitive=False
                )
            except (WorkspaceError, FileNotFoundError) as exc:
                raise TestPolicyError(
                    f"Target file in node selector rejected: {exc}",
                    TestErrorCode.UNAUTHORIZED_TARGET,
                ) from None

            if not valid_path.is_file():
                raise TestPolicyError(
                    f"Target '{file_part}' is not a regular file.",
                    TestErrorCode.UNAUTHORIZED_TARGET,
                )

            rel_file = valid_path.relative_to(workspace_manager.root).as_posix()
            return f"{rel_file}::{'::'.join(node_parts)}"

        # Check Python module format (e.g. tests.test_example) for unittest
        if "." in clean_target and "/" not in clean_target and "\\" not in clean_target:
            module_rel = "/".join(clean_target.split("."))
            py_cand = f"{module_rel}.py"
            try:
                workspace_manager.validate_path(py_cand, must_exist=True, allow_sensitive=False)
                return clean_target
            except (WorkspaceError, FileNotFoundError):
                init_cand = f"{module_rel}/__init__.py"
                try:
                    workspace_manager.validate_path(
                        init_cand, must_exist=True, allow_sensitive=False
                    )
                    return clean_target
                except (WorkspaceError, FileNotFoundError):
                    pass

        # Standard file or directory target
        try:
            valid_path = workspace_manager.validate_path(
                clean_target, must_exist=True, allow_sensitive=False
            )
        except (WorkspaceError, FileNotFoundError) as exc:
            raise TestPolicyError(
                f"Target test path rejected: {exc}",
                TestErrorCode.UNAUTHORIZED_TARGET,
            ) from None

        if valid_path.is_file() and not valid_path.name.endswith(".py"):
            raise TestPolicyError(
                f"Target test file '{valid_path.name}' must be a Python (.py) file.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        return valid_path.relative_to(workspace_manager.root).as_posix()

    def validate_options(
        self,
        framework: TestFramework,
        options: Sequence[str] | None,
    ) -> list[str]:
        """Validate and positively allowlist CLI options."""
        if not options:
            return []

        if len(options) > self.MAX_ARGUMENTS:
            raise TestPolicyError(
                f"Too many test options provided ({len(options)} > max {self.MAX_ARGUMENTS}).",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        validated: list[str] = []
        i = 0
        raw = list(options)

        while i < len(raw):
            opt = raw[i].strip()

            if framework == TestFramework.UNITTEST:
                # Unittest allows only safe verbosity flags
                if opt in ("-v", "-q"):
                    validated.append(opt)
                    i += 1
                    continue
                raise TestPolicyError(
                    f"Option '{opt}' is not permitted for unittest framework. Only '-v' and '-q' are allowed.",
                    TestErrorCode.INVALID_ARGUMENTS,
                )

            # Pytest options positive allowlist
            if opt in self.ALLOWED_BOOLEAN_FLAGS:
                validated.append(opt)
                i += 1
                continue

            # Check -k <expr>
            if opt == "-k":
                if i + 1 >= len(raw):
                    raise TestPolicyError(
                        "Option '-k' requires an expression argument.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                expr = self.filter_validator.validate(raw[i + 1], option_name="-k")
                validated.extend(["-k", expr])
                i += 2
                continue

            if opt.startswith("-k="):
                expr = self.filter_validator.validate(opt[3:], option_name="-k")
                validated.append(f"-k={expr}")
                i += 1
                continue

            # Check -m <marker>
            if opt == "-m":
                if i + 1 >= len(raw):
                    raise TestPolicyError(
                        "Option '-m' requires a marker expression argument.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                marker_expr = self.filter_validator.validate(raw[i + 1], option_name="-m")
                validated.extend(["-m", marker_expr])
                i += 2
                continue

            if opt.startswith("-m="):
                marker_expr = self.filter_validator.validate(opt[3:], option_name="-m")
                validated.append(f"-m={marker_expr}")
                i += 1
                continue

            # Check --tb=<style>
            if opt.startswith("--tb="):
                tb_val = opt[5:].lower()
                if tb_val not in self.ALLOWED_TB_VALUES:
                    raise TestPolicyError(
                        f"Invalid traceback style '{tb_val}'. Allowed: {sorted(self.ALLOWED_TB_VALUES)}.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                validated.append(opt)
                i += 1
                continue

            # Check --maxfail=<N>
            if opt.startswith("--maxfail="):
                val_str = opt[10:]
                if not val_str.isdigit() or int(val_str) <= 0:
                    raise TestPolicyError(
                        f"Option '--maxfail' requires a positive integer value, got '{val_str}'.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                validated.append(opt)
                i += 1
                continue

            # Check --durations=<N>
            if opt.startswith("--durations="):
                val_str = opt[12:]
                if not val_str.isdigit() or int(val_str) < 0:
                    raise TestPolicyError(
                        f"Option '--durations' requires a non-negative integer value, got '{val_str}'.",
                        TestErrorCode.INVALID_ARGUMENTS,
                    )
                validated.append(opt)
                i += 1
                continue

            # Everything else is rejected
            raise TestPolicyError(
                f"Option '{opt}' is not in the approved positive allowlist for test execution.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        return validated

    def sanitize_environment(self) -> dict[str, str]:
        """Produce sanitized environment removing secrets and Python injection vectors."""
        clean_env: dict[str, str] = {}
        for k, v in os.environ.items():
            k_upper = k.upper()
            if k_upper.startswith("GIT_"):
                continue
            if any(p in k_upper for p in CommandExecutor.SENSITIVE_ENV_PATTERNS):
                continue
            if k_upper in CommandExecutor.PYTHON_INJECTION_VARS:
                continue
            clean_env[k] = v

        # Prevent pytest terminal prompt / pagination / colors
        clean_env["PYTHONUNBUFFERED"] = "1"
        clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
        clean_env["TERM"] = "dumb"
        clean_env["NO_COLOR"] = "1"
        return clean_env

    def build_sanitized_env(self) -> dict[str, str]:
        """Alias for sanitize_environment."""
        return self.sanitize_environment()

    def build_command(
        self,
        framework: TestFramework | str,
        targets: Sequence[str] | str | None = None,
        options: Sequence[str] | None = None,
    ) -> list[str]:
        """Construct authoritative command argv for test execution."""
        clean_fw_str = str(framework).strip().lower()
        if clean_fw_str == "pytest" or framework == TestFramework.PYTEST:
            fw = TestFramework.PYTEST
        elif clean_fw_str == "unittest" or framework == TestFramework.UNITTEST:
            fw = TestFramework.UNITTEST
        else:
            raise TestPolicyError(
                f"Unsupported test framework '{framework}'. Only 'pytest' and 'unittest' are supported.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        target_list: list[str] = []
        if targets:
            raw_targets = [targets] if isinstance(targets, str) else list(targets)
            if len(raw_targets) > self.MAX_TARGETS:
                raise TestPolicyError(
                    f"Too many target paths ({len(raw_targets)} > max {self.MAX_TARGETS}).",
                    TestErrorCode.INVALID_ARGUMENTS,
                )
            for t in raw_targets:
                target_list.append(self.validate_target(t))

        validated_options = self.validate_options(fw, options)
        python_exe = self.resolve_python_executable()

        if fw == TestFramework.PYTEST:
            hardening_flags = ["-o", "console_output_style=classic"]
            return (
                [str(python_exe), "-m", "pytest"]
                + hardening_flags
                + validated_options
                + target_list
            )
        else:
            return [str(python_exe), "-m", "unittest"] + validated_options + target_list


class TestRunner:
    """Orchestrates controlled test execution, timeout bounds, and structured parsing."""

    __test__ = False

    PYTEST_SUMMARY_REGEX = re.compile(
        r"=+ (?:(?P<passed>\d+) passed)?(?:, )?"
        r"(?:(?P<failed>\d+) failed)?(?:, )?"
        r"(?:(?P<skipped>\d+) skipped)?(?:, )?"
        r"(?:(?P<errors>\d+) errors?)?"
        r".*? in (?P<duration>[\d\.]+)s =+",
        re.IGNORECASE,
    )

    UNITTEST_SUMMARY_REGEX = re.compile(
        r"Ran (?P<total>\d+) tests? in (?P<duration>[\d\.]+)s\s*\n\s*(?P<status>OK|FAILED(?:\s*\([^\)]+\))?)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        policy: TestExecutionPolicy | None = None,
        process_runner: Callable[..., Any] | None = None,
    ) -> None:
        self.policy = policy or TestExecutionPolicy()
        self.process_runner = process_runner

    def parse_test_output(
        self,
        framework: TestFramework,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        timed_out: bool,
    ) -> tuple[str, TestSummary, list[dict[str, str]]]:
        """Parse structured test status and counts deterministically without executing twice."""
        summary = TestSummary()
        failures: list[dict[str, str]] = []

        if timed_out:
            return (
                "timeout",
                summary,
                [{"node": "execution", "message": "Test execution timed out."}],
            )

        if exit_code is None:
            return (
                "error",
                summary,
                [{"node": "execution", "message": "Process execution failed without exit code."}],
            )

        combined_output = f"{stdout}\n{stderr}"

        if framework == TestFramework.PYTEST:
            # Search for pytest summary line: =+ ... in X.XXs =+
            summary_match = re.search(
                r"=+\s*(.*?)\s+in\s+([\d\.]+)s\s*=+", combined_output, re.IGNORECASE
            )
            if summary_match:
                content = summary_match.group(1)
                dur_str = summary_match.group(2)
                summary.duration_seconds = float(dur_str) if dur_str else None

                p_m = re.search(r"(\d+)\s+passed", content, re.IGNORECASE)
                f_m = re.search(r"(\d+)\s+failed", content, re.IGNORECASE)
                s_m = re.search(r"(\d+)\s+skipped", content, re.IGNORECASE)
                e_m = re.search(r"(\d+)\s+errors?", content, re.IGNORECASE)

                summary.passed = int(p_m.group(1)) if p_m else 0
                summary.failed = int(f_m.group(1)) if f_m else 0
                summary.skipped = int(s_m.group(1)) if s_m else 0
                summary.errors = int(e_m.group(1)) if e_m else 0
                summary.total = summary.passed + summary.failed + summary.skipped + summary.errors

            # Extract failure header snippets
            for line in combined_output.splitlines():
                if line.startswith(("FAILED ", "ERROR ")):
                    parts = line.split(" - ", 1)
                    node = parts[0].replace("FAILED ", "").replace("ERROR ", "").strip()
                    msg = parts[1].strip() if len(parts) > 1 else line.strip()
                    failures.append({"name": node, "node": node, "message": msg})
                elif line.startswith("____") and line.endswith("____"):
                    clean_name = line.strip("_ \t")
                    if clean_name and not any(f.get("name") == clean_name for f in failures):
                        failures.append(
                            {
                                "name": clean_name,
                                "node": clean_name,
                                "message": "Test failed",
                            }
                        )

            if exit_code == 0:
                status = "passed"
            elif exit_code == 5:
                status = "no_tests_collected"
            elif exit_code == 1:
                status = "failed"
            else:
                status = "error"

        else:  # UNITTEST
            match = self.UNITTEST_SUMMARY_REGEX.search(combined_output)
            if match:
                summary.total = int(match.group("total") or 0)
                dur_str = match.group("duration")
                summary.duration_seconds = float(dur_str) if dur_str else None
                u_status = match.group("status")
                if "FAILED" in u_status:
                    # Look for failures/errors count in parentheses
                    f_match = re.search(r"failures=(\d+)", u_status)
                    e_match = re.search(r"errors=(\d+)", u_status)
                    summary.failed = int(f_match.group(1)) if f_match else 1
                    summary.errors = int(e_match.group(1)) if e_match else 0
                    summary.passed = max(0, summary.total - summary.failed - summary.errors)
                else:
                    summary.passed = summary.total

            if exit_code == 0:
                status = "passed"
            else:
                status = "failed"

        return status, summary, failures

    def run_tests(
        self,
        framework: str = "pytest",
        targets: Sequence[str] | str | None = None,
        options: Sequence[str] | None = None,
        timeout: float = 30.0,
    ) -> TestResult:
        """Execute controlled tests inside authorized workspace."""
        clean_fw_str = str(framework).strip().lower()
        if clean_fw_str == "pytest":
            fw = TestFramework.PYTEST
        elif clean_fw_str == "unittest":
            fw = TestFramework.UNITTEST
        else:
            raise TestPolicyError(
                f"Unsupported test framework '{framework}'. Only 'pytest' and 'unittest' are supported.",
                TestErrorCode.INVALID_ARGUMENTS,
            )

        workspace_root = workspace_manager.root

        # Clamp timeout
        clamped_timeout = max(
            self.policy.MIN_TIMEOUT,
            min(float(timeout), self.policy.MAX_TIMEOUT),
        )

        clean_env = self.policy.sanitize_environment()

        # Build authoritative argv via policy
        cmd_argv = self.policy.build_command(fw, targets=targets, options=options)

        display_cmd = " ".join(cmd_argv)
        logger.info(
            "Executing controlled test: framework={}, argv={}, cwd={}",
            fw.value,
            cmd_argv,
            workspace_root,
        )

        runner = self.process_runner or subprocess.run
        timed_out = False
        exit_code: int | None = None
        stdout_str = ""
        stderr_str = ""
        truncated = False

        try:
            proc = runner(
                cmd_argv,
                cwd=str(workspace_root),
                env=clean_env,
                shell=False,
                capture_output=True,
                timeout=clamped_timeout,
            )
            exit_code = getattr(proc, "returncode", 0)
            raw_stdout = getattr(proc, "stdout", b"") or b""
            raw_stderr = getattr(proc, "stderr", b"") or b""

            if isinstance(raw_stdout, str):
                raw_stdout = raw_stdout.encode("utf-8", errors="replace")
            if isinstance(raw_stderr, str):
                raw_stderr = raw_stderr.encode("utf-8", errors="replace")

            notice = b"\n[TEST OUTPUT TRUNCATED: 64 KB limit exceeded]"
            if len(raw_stdout) > self.policy.DEFAULT_MAX_OUTPUT_BYTES:
                allowed_len = max(0, self.policy.DEFAULT_MAX_OUTPUT_BYTES - len(notice))
                raw_stdout = raw_stdout[:allowed_len] + notice
                truncated = True
            if len(raw_stderr) > self.policy.DEFAULT_MAX_OUTPUT_BYTES:
                allowed_len = max(0, self.policy.DEFAULT_MAX_OUTPUT_BYTES - len(notice))
                raw_stderr = raw_stderr[:allowed_len] + notice
                truncated = True

            stdout_str = raw_stdout.decode("utf-8", errors="replace")
            stderr_str = raw_stderr.decode("utf-8", errors="replace")

        except subprocess.TimeoutExpired:
            timed_out = True
            stderr_str = f"Test execution timed out after {clamped_timeout} seconds."
        except Exception as exc:  # noqa: BLE001
            stderr_str = f"Process execution failed: {exc}"

        status, summary, failures = self.parse_test_output(
            fw, exit_code, stdout_str, stderr_str, timed_out
        )

        return TestResult(
            success=(status == "passed"),
            framework=fw.value,
            command=display_cmd,
            exit_code=exit_code,
            status=status,
            summary=summary,
            failures=failures,
            timed_out=timed_out,
            truncated=truncated,
            stdout=stdout_str,
            stderr=stderr_str,
            cwd=str(workspace_root),
        )


test_runner = TestRunner()
