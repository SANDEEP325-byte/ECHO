from packages.interfaces.security import RiskLevel

class RiskClassifier:
    """Classifies ECHO operations according to their security risk."""

    SAFE_OPERATIONS = {
        "calculator",
        "time",
        "date",
        "read_file",
        "search",
        "weather",
    }

    MODERATE_OPERATIONS = {
        "terminal",
        "open_vscode",
        "open_chrome",
        "run_npm",
    }

    SENSITIVE_OPERATIONS = {
        "delete_file",
        "delete_folder",
        "rename_file",
        "rename_folder",
        "git_push",
    }

    CRITICAL_OPERATIONS = {
        "format_drive",
        "remove_repository",
        "massive_delete",
    }

    @classmethod
    def classify(cls, operation: str) -> RiskLevel:
        """Return the risk level associated with an operation."""

        normalized = operation.strip().lower()

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