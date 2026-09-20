from typing import Any, ClassVar

from packages.interfaces.security import RiskLevel


class RiskClassifier:
    """Classifies ECHO operations according to their security risk."""

    SAFE_OPERATIONS: ClassVar[set[str]] = {
        "calculator",
        "time",
        "date",
        "read_file",
        "list_folder",
        "create_folder",
        "open_file",
        "open_folder",
        "search",
        "weather",
        "browser_read_page",
        "inspect_code_tree",
        "search_code",
        "read_code",
    }

    MODERATE_OPERATIONS: ClassVar[set[str]] = {
        "terminal",
        "open_vscode",
        "open_chrome",
        "run_npm",
        "copy_file",
        "open_application",
        "browser_navigate",
        "browser_click",
        "browser_type",
    }

    SENSITIVE_OPERATIONS: ClassVar[set[str]] = {
        "delete_file",
        "delete_folder",
        "rename_file",
        "rename_folder",
        "move_file",
        "create_file",
        "git_push",
        "execute_command",
        "run_command",
        "browser_download",
        "browser_upload",
        "modify_code",
        "apply_patch",
        "run_tests",
    }

    CRITICAL_OPERATIONS: ClassVar[set[str]] = {
        "format_drive",
        "remove_repository",
        "massive_delete",
    }

    DANGEROUS_PATTERNS = (
        "format",
        "rm -rf",
        "rmdir /s",
        "del /s",
        "drop table",
        "drop database",
        "truncate",
        "remove_repository",
        "massive_delete",
        ":(){ :|:& };:",
    )

    SENSITIVE_PATTERNS = (
        "delete",
        "unlink",
        "remove",
        "destroy",
        "kill",
        "pkill",
        "overwrite",
        "chmod",
        "chown",
        "passwd",
    )

    @classmethod
    def classify(
        cls,
        operation: str,
        arguments: dict[str, Any] | None = None,
    ) -> RiskLevel:
        """Return the risk level associated with an operation and optional arguments."""

        normalized = operation.strip().lower()

        # 1. Payload inspection for dangerous terms
        if arguments:

            def _get_arg_values(key_name: str) -> list[Any]:
                return [v for k, v in arguments.items() if str(k).lower() == key_name]

            payload_str = " ".join(str(v).lower() for v in arguments.values())
            if any(pattern in payload_str for pattern in cls.DANGEROUS_PATTERNS):
                return RiskLevel.CRITICAL
            if any(pattern in payload_str for pattern in cls.SENSITIVE_PATTERNS):
                return RiskLevel.SENSITIVE

            # Specific browser interaction classification
            if normalized == "browser_click":
                if any(v is True for v in _get_arg_values("is_submit")):
                    return RiskLevel.SENSITIVE
                selectors = [str(v).lower() for v in _get_arg_values("selector")]
                browser_sensitive_click_keywords = (
                    "submit",
                    "buy",
                    "purchase",
                    "delete",
                    "remove",
                    "pay",
                    "checkout",
                    "transfer",
                    "login",
                    "logout",
                    "confirm",
                    "publish",
                    "create",
                    "account",
                )
                if any(k in sel for sel in selectors for k in browser_sensitive_click_keywords):
                    return RiskLevel.SENSITIVE

            if normalized == "browser_type":
                if any(v is True for v in _get_arg_values("is_sensitive")) or any(
                    v is True for v in _get_arg_values("submit")
                ):
                    return RiskLevel.SENSITIVE
                selectors = [str(v).lower() for v in _get_arg_values("selector")]
                sensitive_field_keywords = (
                    "password",
                    "pass",
                    "pwd",
                    "secret",
                    "token",
                    "key",
                    "pin",
                    "ssn",
                    "credit",
                    "card",
                    "cvv",
                    "auth",
                )
                if any(k in sel for sel in selectors for k in sensitive_field_keywords):
                    return RiskLevel.SENSITIVE

            if normalized == "browser_download":
                dest_vals = [str(v).lower() for v in _get_arg_values("destination_path")]
                dangerous_exts = (
                    ".exe",
                    ".bat",
                    ".cmd",
                    ".ps1",
                    ".vbs",
                    ".js",
                    ".msi",
                    ".dll",
                    ".sys",
                    ".scr",
                )
                if any(
                    any(dest.endswith(ext) for ext in dangerous_exts) or dest.startswith(r"\\")
                    for dest in dest_vals
                ):
                    return RiskLevel.CRITICAL
                if dest_vals:
                    return RiskLevel.SENSITIVE

            if normalized == "browser_upload":
                src_vals = [str(v).lower() for v in _get_arg_values("file_path")]
                sensitive_targets = (
                    "id_rsa",
                    "id_ed25519",
                    ".pem",
                    ".key",
                    "credentials",
                    ".secrets",
                    ".ssh",
                    ".aws",
                )
                if any(
                    any(t in src for t in sensitive_targets) or src.startswith(r"\\")
                    for src in src_vals
                ):
                    return RiskLevel.CRITICAL
                if src_vals:
                    return RiskLevel.SENSITIVE

        # 2. Base operation classification
        if normalized in cls.SAFE_OPERATIONS:
            return RiskLevel.SAFE

        if normalized in cls.MODERATE_OPERATIONS:
            return RiskLevel.MODERATE

        if normalized in cls.SENSITIVE_OPERATIONS:
            return RiskLevel.SENSITIVE

        if normalized in cls.CRITICAL_OPERATIONS:
            return RiskLevel.CRITICAL

        # Unknown operations must never be treated as safe.
        return RiskLevel.SENSITIVE


risk_classifier = RiskClassifier()
