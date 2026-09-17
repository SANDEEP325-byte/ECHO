from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Sequence

from services.desktop.policy import (
    DesktopSecurityPolicy,
    desktop_security_policy,
    OperationType,
)
from services.logging.logger import logger


class CommandErrorCode(str, Enum):
    """Structured error codes for command execution policy violations and failures."""

    COMMAND_NOT_ALLOWED = "command_not_allowed"
    EXECUTABLE_NOT_TRUSTED = "executable_not_trusted"
    INVALID_ARGUMENTS = "invalid_arguments"
    INVALID_WORKING_DIRECTORY = "invalid_working_directory"
    TIMEOUT = "timeout"
    EXECUTION_FAILED = "execution_failed"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    POLICY_BLOCKED = "policy_blocked"


class CommandPolicyError(PermissionError):
    """Raised when a command execution request violates the security policy."""

    def __init__(self, reason: str, error_code: CommandErrorCode) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_code = error_code


class CommandExecutionPolicy:
    """Policy engine governing allowlisted, structured command execution."""

    ALLOWED_FAMILIES = {"git", "python"}

    FORBIDDEN_INTERPRETERS = {
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "bash",
        "bash.exe",
        "sh",
        "sh.exe",
        "wscript",
        "wscript.exe",
        "cscript",
        "cscript.exe",
        "mshta",
        "mshta.exe",
    }

    FORBIDDEN_SHELL_PATTERNS = (
        "&",
        "|",
        ";",
        ">",
        "<",
        "`",
        "$(",
        "${",
        "\n",
        "\r",
        "\x00",
    )

    ALLOWED_GIT_SUBCOMMANDS = {"status", "log", "diff"}

    # Strict argument allowlists per Git subcommand
    ALLOWED_GIT_STATUS_FLAGS = {
        "--short",
        "-s",
        "--branch",
        "-b",
        "--porcelain",
        "--ignored",
    }

    ALLOWED_GIT_LOG_FLAGS = {
        "--oneline",
        "--stat",
        "-p",
        "--graph",
        "--no-ext-diff",
        "--no-textconv",
    }

    ALLOWED_GIT_DIFF_FLAGS = {
        "--stat",
        "--name-only",
        "--staged",
        "--cached",
        "--no-ext-diff",
        "--no-textconv",
        "head",
    }

    ALLOWED_PYTHON_ARGS = (
        ("--version",),
        ("-v",),
        ("-vv",),
    )

    def __init__(
        self,
        desktop_policy: DesktopSecurityPolicy | None = None,
        trusted_roots: Sequence[Path | str] | None = None,
    ) -> None:
        self.desktop_policy = desktop_policy or desktop_security_policy
        self._custom_trusted_roots = [Path(r).resolve() for r in trusted_roots] if trusted_roots else None

    def validate_command_identifier(self, command_name: str) -> str:
        """Validate and normalize a command family identifier."""
        if not command_name or not isinstance(command_name, str):
            raise CommandPolicyError(
                "Command identifier must be a non-empty string.",
                CommandErrorCode.INVALID_ARGUMENTS,
            )

        clean = command_name.strip().lower()
        if not clean:
            raise CommandPolicyError(
                "Command identifier cannot be blank.",
                CommandErrorCode.INVALID_ARGUMENTS,
            )

        # Reject path separators, special characters, and extensions
        if any(c in clean for c in ("/\\:*?\"<>|\x00")):
            raise CommandPolicyError(
                f"Command identifier '{command_name}' contains prohibited path or special characters.",
                CommandErrorCode.COMMAND_NOT_ALLOWED,
            )

        # Reject direct shell interpreters
        if clean in self.FORBIDDEN_INTERPRETERS:
            raise CommandPolicyError(
                f"Shell interpreter '{command_name}' is strictly prohibited.",
                CommandErrorCode.COMMAND_NOT_ALLOWED,
            )

        # Reject executable and script extensions
        if clean.endswith((".exe", ".bat", ".cmd", ".ps1", ".vbs", ".sh", ".py", ".msi", ".com")):
            raise CommandPolicyError(
                f"Executable or script extensions in command identifier '{command_name}' are prohibited.",
                CommandErrorCode.COMMAND_NOT_ALLOWED,
            )

        if clean not in self.ALLOWED_FAMILIES:
            raise CommandPolicyError(
                f"Command family '{command_name}' is not in the approved allowlist.",
                CommandErrorCode.COMMAND_NOT_ALLOWED,
            )

        return clean

    def _get_trusted_roots(self) -> list[Path]:
        """Return the strict list of administrator-controlled installation roots."""
        if self._custom_trusted_roots is not None:
            return list(self._custom_trusted_roots)

        roots: list[Path] = []
        for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
            val = os.environ.get(env_var)
            if val:
                try:
                    p = Path(val).resolve()
                    if p.exists() and p not in roots:
                        roots.append(p)
                except Exception:
                    pass

        # Windows System32
        win_dir = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
        try:
            sys32 = (Path(win_dir) / "System32").resolve()
            if sys32.exists() and sys32 not in roots:
                roots.append(sys32)
        except Exception:
            pass

        return roots

    def _is_in_trusted_root(self, path: Path) -> bool:
        """Check whether the resolved path resides strictly inside an explicitly trusted root."""
        resolved = path.resolve()

        if self._custom_trusted_roots is not None:
            # When custom trusted roots are configured (e.g. testing or explicit deployment policy),
            # the executable must reside strictly within one of the custom trusted roots.
            for root in self._custom_trusted_roots:
                if self._is_subpath(resolved, root):
                    return True
            return False

        # In production (default roots), enforce strict defense-in-depth:
        # Never allow executables in user home (AppData, Desktop, Documents, Downloads, etc.)
        home = Path.home().resolve()
        if self._is_subpath(resolved, home):
            return False

        # Never allow executables in temporary directories
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if self._is_subpath(resolved, temp_dir):
            return False

        # Never allow executables in workspace
        workspace = Path.cwd().resolve()
        if self._is_subpath(resolved, workspace):
            return False

        # Must reside inside one of the explicitly trusted roots
        for root in self._get_trusted_roots():
            if self._is_subpath(resolved, root):
                return True

        return False

    @staticmethod
    def _is_subpath(child: Path, parent: Path) -> bool:
        """Component-aware check if child resides within parent."""
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def resolve_executable(self, command_family: str) -> Path:
        """Resolve a command family identifier to a verified executable in a trusted location."""
        canonical = self.validate_command_identifier(command_family)

        candidates: list[Path] = []

        if canonical == "git":
            for pf in self._get_trusted_roots():
                candidates.extend([
                    pf / "Git" / "cmd" / "git.exe",
                    pf / "Git" / "bin" / "git.exe",
                    pf / "git.exe",
                ])

            which_git = shutil.which("git")
            if which_git:
                candidates.append(Path(which_git))

        elif canonical == "python":
            base_prefix = Path(sys.base_prefix).resolve()
            candidates.append(base_prefix / "python.exe")

            for pf in self._get_trusted_roots():
                for ver in ["Python312", "Python311", "Python310", "Python313", "Python39"]:
                    candidates.append(pf / ver / "python.exe")

            which_python = shutil.which("python")
            if which_python:
                candidates.append(Path(which_python))

        for candidate in candidates:
            if not candidate:
                continue
            resolved = candidate.resolve(strict=False)
            if resolved.is_file() and self._is_in_trusted_root(resolved):
                return resolved

        raise CommandPolicyError(
            f"Executable for '{canonical}' could not be resolved in a trusted system location.",
            CommandErrorCode.EXECUTABLE_NOT_TRUSTED,
        )

    def validate_arguments(
        self,
        command_family: str,
        arguments: Sequence[str] | None,
    ) -> list[str]:
        """Validate argument list for safety, shell metacharacters, and strict allowlists."""
        canonical = self.validate_command_identifier(command_family)

        if arguments is None:
            raw_args: list[str] = []
        elif isinstance(arguments, (list, tuple)):
            raw_args = list(arguments)
        else:
            raise CommandPolicyError(
                "Command arguments must be provided as a structured list of strings, not a command string.",
                CommandErrorCode.INVALID_ARGUMENTS,
            )

        sanitized_args: list[str] = []

        for arg in raw_args:
            if not isinstance(arg, str):
                raise CommandPolicyError(
                    f"Invalid argument type '{type(arg).__name__}'. All arguments must be strings.",
                    CommandErrorCode.INVALID_ARGUMENTS,
                )

            # Check for forbidden shell metacharacters
            for pattern in self.FORBIDDEN_SHELL_PATTERNS:
                if pattern in arg:
                    raise CommandPolicyError(
                        f"Forbidden shell metacharacter '{pattern}' detected in argument '{arg}'.",
                        CommandErrorCode.INVALID_ARGUMENTS,
                    )

            sanitized_args.append(arg)

        # Command-family specific strict allowlisting
        if canonical == "git":
            if not sanitized_args:
                raise CommandPolicyError(
                    "Git execution requires a safe subcommand (e.g. 'status', 'log', 'diff').",
                    CommandErrorCode.INVALID_ARGUMENTS,
                )

            subcmd = sanitized_args[0].lower()

            if subcmd not in self.ALLOWED_GIT_SUBCOMMANDS:
                raise CommandPolicyError(
                    f"Git subcommand '{subcmd}' is not allowed. Only 'status', 'log', 'diff' are supported.",
                    CommandErrorCode.INVALID_ARGUMENTS,
                )

            sub_args = sanitized_args[1:]

            if subcmd == "status":
                for arg in sub_args:
                    if arg.lower() not in self.ALLOWED_GIT_STATUS_FLAGS:
                        raise CommandPolicyError(
                            f"Argument '{arg}' is not in the approved allowlist for 'git status'.",
                            CommandErrorCode.INVALID_ARGUMENTS,
                        )

            elif subcmd == "log":
                i = 0
                while i < len(sub_args):
                    arg = sub_args[i]
                    arg_lower = arg.lower()

                    if arg_lower in self.ALLOWED_GIT_LOG_FLAGS:
                        i += 1
                        continue

                    # Support '-n <positive_integer>'
                    if arg_lower == "-n":
                        if i + 1 < len(sub_args):
                            count_val = sub_args[i + 1]
                            if not count_val.isdigit() or int(count_val) <= 0:
                                raise CommandPolicyError(
                                    f"Git log '-n' option requires a positive integer, got '{count_val}'.",
                                    CommandErrorCode.INVALID_ARGUMENTS,
                                )
                            i += 2
                            continue
                        else:
                            raise CommandPolicyError(
                                "Git log '-n' option requires a positive integer value.",
                                CommandErrorCode.INVALID_ARGUMENTS,
                            )

                    # Support '-<positive_integer>' (e.g. '-5')
                    if arg.startswith("-") and len(arg) > 1 and arg[1:].isdigit():
                        if int(arg[1:]) <= 0:
                            raise CommandPolicyError(
                                f"Git log limit must be a positive integer, got '{arg}'.",
                                CommandErrorCode.INVALID_ARGUMENTS,
                            )
                        i += 1
                        continue

                    raise CommandPolicyError(
                        f"Argument '{arg}' is not in the approved allowlist for 'git log'.",
                        CommandErrorCode.INVALID_ARGUMENTS,
                    )

            elif subcmd == "diff":
                for arg in sub_args:
                    if arg.lower() not in self.ALLOWED_GIT_DIFF_FLAGS:
                        raise CommandPolicyError(
                            f"Argument '{arg}' is not in the approved allowlist for 'git diff'.",
                            CommandErrorCode.INVALID_ARGUMENTS,
                        )

        elif canonical == "python":
            if not sanitized_args:
                raise CommandPolicyError(
                    "Python execution requires safe arguments (e.g. ['--version']).",
                    CommandErrorCode.INVALID_ARGUMENTS,
                )

            # Normalize arguments tuple
            norm_args = tuple(a.lower() for a in sanitized_args)
            if norm_args not in self.ALLOWED_PYTHON_ARGS:
                raise CommandPolicyError(
                    "Python execution is strictly limited to version interrogation ('--version', '-V'). Arbitrary code/script execution is prohibited.",
                    CommandErrorCode.INVALID_ARGUMENTS,
                )

        return sanitized_args

    def validate_cwd(self, cwd: str | Path | None) -> Path:
        """Validate that working directory exists and resides within authorized sandbox roots."""
        if cwd is None:
            return Path.cwd().resolve()

        if not isinstance(cwd, (str, Path)) or not str(cwd).strip():
            raise CommandPolicyError(
                "Working directory path must be a non-empty string or Path.",
                CommandErrorCode.INVALID_WORKING_DIRECTORY,
            )

        # Validate through existing DesktopSecurityPolicy sandbox
        check_result = self.desktop_policy.validate(cwd, OperationType.READ)
        if not check_result.allowed:
            raise CommandPolicyError(
                f"Working directory rejected: {check_result.reason}",
                CommandErrorCode.INVALID_WORKING_DIRECTORY,
            )

        resolved_cwd = Path(check_result.target_path or cwd).resolve()

        if not resolved_cwd.exists():
            raise CommandPolicyError(
                f"Working directory does not exist: '{cwd}'.",
                CommandErrorCode.INVALID_WORKING_DIRECTORY,
            )

        if not resolved_cwd.is_dir():
            raise CommandPolicyError(
                f"Working directory must be a directory, not a file: '{cwd}'.",
                CommandErrorCode.INVALID_WORKING_DIRECTORY,
            )

        return resolved_cwd


class CommandExecutor:
    """Executes controlled commands via structured subprocess without shell invocation."""

    DEFAULT_TIMEOUT = 15.0
    DEFAULT_MAX_OUTPUT_BYTES = 65536  # 64 KB

    SENSITIVE_ENV_PATTERNS = (
        "KEY",
        "SECRET",
        "TOKEN",
        "PASSWORD",
        "CREDENTIAL",
        "AUTH",
        "API",
    )

    PYTHON_INJECTION_VARS = (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONINSPECT",
        "PYTHONBREAKPOINT",
        "PYTHONWARNINGS",
    )

    def __init__(
        self,
        policy: CommandExecutionPolicy | None = None,
        process_runner: Callable[..., Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        self.policy = policy or CommandExecutionPolicy()
        self.process_runner = process_runner
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes

    def _sanitize_environment(self) -> dict[str, str]:
        """Produce a sanitized baseline environment scrubbing sensitive secrets and injection vectors."""
        clean_env: dict[str, str] = {}

        for key, value in os.environ.items():
            key_upper = key.upper()

            # Scrub all GIT execution, configuration, and hook variables
            if key_upper.startswith("GIT_"):
                continue

            # Scrub known secret and token patterns
            if any(pattern in key_upper for pattern in self.SENSITIVE_ENV_PATTERNS):
                continue

            # Scrub Python injection vectors
            if key_upper in self.PYTHON_INJECTION_VARS:
                continue

            clean_env[key] = value

        # Set safe non-execution Git defaults
        clean_env["GIT_TERMINAL_PROMPT"] = "0"
        clean_env["GIT_OPTIONAL_LOCKS"] = "0"

        return clean_env

    def execute_command(
        self,
        command: str,
        arguments: Sequence[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Safely execute an allowlisted command family with structured arguments."""
        if env is not None:
            raise CommandPolicyError(
                "Custom environment variables supplied by user or request are prohibited.",
                CommandErrorCode.POLICY_BLOCKED,
            )

        family = self.policy.validate_command_identifier(command)
        executable_path = self.policy.resolve_executable(family)
        sanitized_args = self.policy.validate_arguments(family, arguments)
        resolved_cwd = self.policy.validate_cwd(cwd)

        clean_env = self._sanitize_environment()

        # Build authoritative argv with hardening configuration
        if family == "git":
            subcmd = sanitized_args[0].lower()
            user_options = sanitized_args[1:]

            # Authoritative hardening options placed before subcommand to override any repo/global config
            git_global_hardening = [
                "--no-pager",
                "-c", "core.fsmonitor=false",
                "-c", "diff.external=",
                "-c", "core.pager=",
                "-c", "filter.lfs.clean=",
                "-c", "filter.lfs.smudge=",
            ]

            subcmd_hardening: list[str] = []
            if subcmd in ("diff", "log"):
                subcmd_hardening.extend(["--no-ext-diff", "--no-textconv"])

            cmd_argv = (
                [str(executable_path)]
                + git_global_hardening
                + [subcmd]
                + subcmd_hardening
                + user_options
            )
        else:
            cmd_argv = [str(executable_path)] + sanitized_args

        logger.info(
            "Executing controlled command: family={}, argv={}, cwd={}",
            family,
            cmd_argv,
            resolved_cwd,
        )

        runner = self.process_runner or subprocess.run

        try:
            proc = runner(
                cmd_argv,
                cwd=str(resolved_cwd),
                env=clean_env,
                shell=False,
                capture_output=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Command execution timed out after {}s: family={}, args={}",
                self.timeout,
                family,
                sanitized_args,
            )
            return {
                "operation": "execute_command",
                "command": family,
                "arguments": sanitized_args,
                "cwd": str(resolved_cwd),
                "exit_code": None,
                "stdout": "",
                "stderr": f"Command timed out after {self.timeout} seconds.",
                "status": "timeout",
                "timed_out": True,
                "truncated": False,
                "verified": False,
            }
        except Exception as exc:
            logger.error("Process execution failed for command '{}': {}", family, exc)
            return {
                "operation": "execute_command",
                "command": family,
                "arguments": sanitized_args,
                "cwd": str(resolved_cwd),
                "exit_code": None,
                "stdout": "",
                "stderr": f"Process execution failed: {exc}",
                "status": "failed",
                "timed_out": False,
                "truncated": False,
                "verified": False,
            }

        # Safe output bounding and truncation
        stdout_bytes = getattr(proc, "stdout", b"") or b""
        stderr_bytes = getattr(proc, "stderr", b"") or b""

        if isinstance(stdout_bytes, str):
            stdout_bytes = stdout_bytes.encode("utf-8", errors="replace")
        if isinstance(stderr_bytes, str):
            stderr_bytes = stderr_bytes.encode("utf-8", errors="replace")

        truncated = False
        if len(stdout_bytes) > self.max_output_bytes:
            stdout_bytes = stdout_bytes[: self.max_output_bytes]
            truncated = True

        if len(stderr_bytes) > self.max_output_bytes:
            stderr_bytes = stderr_bytes[: self.max_output_bytes]
            truncated = True

        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")

        if truncated:
            stdout_str += "\n[OUTPUT TRUNCATED: Exceeded size limit]"

        exit_code = getattr(proc, "returncode", 0)

        return {
            "operation": "execute_command",
            "command": family,
            "arguments": sanitized_args,
            "cwd": str(resolved_cwd),
            "exit_code": exit_code,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "status": "success" if exit_code == 0 else "failed",
            "timed_out": False,
            "truncated": truncated,
            "verified": True,
        }


command_execution_policy = CommandExecutionPolicy()
command_executor = CommandExecutor()
