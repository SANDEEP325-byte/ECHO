from typing import Any

from packages.interfaces.security import RiskLevel

class RiskClassifier:
    """Classifies ECHO operations according to their security risk."""

    SAFE_OPERATIONS = {
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
    }

    MODERATE_OPERATIONS = {
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

    SENSITIVE_OPERATIONS = {
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
    }

    CRITICAL_OPERATIONS = {
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
            payload_str = " ".join(str(v).lower() for v in arguments.values())
            if any(pattern in payload_str for pattern in cls.DANGEROUS_PATTERNS):
                return RiskLevel.CRITICAL
            if any(pattern in payload_str for pattern in cls.SENSITIVE_PATTERNS):
                return RiskLevel.SENSITIVE

            # Specific browser interaction classification
            if normalized == "browser_click":
                if arguments.get("is_submit") is True:
                    return RiskLevel.SENSITIVE
                selector = str(arguments.get("selector", "")).lower()
                browser_sensitive_click_keywords = (
                    "submit", "buy", "purchase", "delete", "remove", "pay", "checkout",
                    "transfer", "login", "logout", "confirm", "publish", "create", "account",
                )
                if any(k in selector for k in browser_sensitive_click_keywords):
                    return RiskLevel.SENSITIVE

            if normalized == "browser_type":
                if arguments.get("is_sensitive") is True or arguments.get("submit") is True:
                    return RiskLevel.SENSITIVE
                selector = str(arguments.get("selector", "")).lower()
                sensitive_field_keywords = (
                    "password", "pass", "pwd", "secret", "token", "key", "pin", "ssn",
                    "credit", "card", "cvv", "auth",
                )
                if any(k in selector for k in sensitive_field_keywords):
                    return RiskLevel.SENSITIVE

            if normalized == "browser_download":
                dest = str(arguments.get("destination_path", "")).lower()
                dangerous_exts = (
                    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".dll", ".sys", ".scr"
                )
                if any(dest.endswith(ext) for ext in dangerous_exts) or dest.startswith(r"\\"):
                    return RiskLevel.CRITICAL
                return RiskLevel.SENSITIVE

            if normalized == "browser_upload":
                src = str(arguments.get("file_path", "")).lower()
                sensitive_targets = (
                    "id_rsa", "id_ed25519", ".pem", ".key", "credentials", ".secrets", ".ssh", ".aws"
                )
                if any(t in src for t in sensitive_targets) or src.startswith(r"\\"):
                    return RiskLevel.CRITICAL
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