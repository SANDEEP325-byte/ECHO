"""Structured error hierarchy for ECHO browser subsystem (Phase 5B).

Provides clear, actionable, and testable error types without leaking
sensitive credentials, internal file paths, or raw stack traces.
"""


class BrowserError(Exception):
    """Base exception for all ECHO browser-related errors."""

    def __init__(self, message: str, code: str = "browser_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        return self.message


class BrowserConfigurationError(BrowserError):
    """Raised when browser service or session configuration is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="browser_configuration_error")


class BrowserUnavailableError(BrowserError):
    """Raised when browser automation dependencies or runtime are unavailable."""

    def __init__(self, message: str, code: str = "browser_unavailable") -> None:
        super().__init__(message, code=code)


class BrowserBinaryMissingError(BrowserUnavailableError):
    """Raised when the Chromium browser executable binary is not found on the system."""

    def __init__(
        self,
        message: str = (
            "Chromium browser binary is not installed. "
            "Please run 'playwright install chromium' to install the required browser."
        ),
    ) -> None:
        super().__init__(message, code="browser_binary_missing")


class BrowserStartupError(BrowserError):
    """Raised when browser process startup fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="browser_startup_error")


class BrowserLifecycleError(BrowserError):
    """Raised when an operation is attempted in an invalid browser lifecycle state."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="browser_lifecycle_error")


class BrowserTimeoutError(BrowserError):
    """Raised when a bounded browser lifecycle operation exceeds its timeout."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="browser_timeout_error")


class BrowserSessionError(BrowserError):
    """Base exception for browser session operations."""

    def __init__(self, message: str, code: str = "browser_session_error") -> None:
        super().__init__(message, code=code)


class BrowserSessionLimitError(BrowserSessionError):
    """Raised when concurrent session limit has been reached."""

    def __init__(self, message: str = "Maximum concurrent browser sessions limit reached.") -> None:
        super().__init__(message, code="browser_session_limit_exceeded")


class BrowserSessionClosedError(BrowserSessionError):
    """Raised when an operation is attempted on an inactive or closed session."""

    def __init__(self, message: str = "Browser session is closed or inactive.") -> None:
        super().__init__(message, code="browser_session_closed")


class BrowserSessionCreationError(BrowserSessionError):
    """Raised when browser context or primary page creation fails."""

    def __init__(self, message: str = "Failed to create browser session context.") -> None:
        super().__init__(message, code="browser_session_creation_failed")
