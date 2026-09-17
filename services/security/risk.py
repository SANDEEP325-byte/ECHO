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
        "search",
        "weather",
    }

    MODERATE_OPERATIONS = {
        "terminal",
        "open_vscode",
        "open_chrome",
        "run_npm",
        "copy_file",
    }

    SENSITIVE_OPERATIONS = {
        "delete_file",
        "delete_folder",
        "rename_file",
        "rename_folder",
        "move_file",
        "create_file",
        "git_push",
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