from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    """Explicit status classification for post-condition verification."""

    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    NOT_APPLICABLE = "not_applicable"
    VERIFICATION_ERROR = "verification_error"


@dataclass(frozen=True)
class VerificationDetail:
    """Detailed post-condition inspection record for an individual operation."""

    operation: str
    status: VerificationStatus
    message: str
    expected: str | None = None
    observed: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "message": self.message,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class VerificationResult:
    """Structured response contract for ECHO verification results."""

    success: bool
    status: VerificationStatus = VerificationStatus.VERIFIED
    result: Any = None
    error: str | None = None
    details: list[VerificationDetail] | None = None

    def __post_init__(self) -> None:
        # Guarantee semantic alignment between boolean success and status enum
        if not self.success and self.status == VerificationStatus.VERIFIED:
            object.__setattr__(self, "status", VerificationStatus.NOT_VERIFIED)
        elif self.success and self.status in (
            VerificationStatus.NOT_VERIFIED,
            VerificationStatus.VERIFICATION_ERROR,
        ):
            object.__setattr__(self, "status", VerificationStatus.VERIFIED)

    def to_dict(self) -> dict[str, Any]:
        """Produce safe structured dictionary representation without technical leakage."""
        return {
            "success": self.success,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "result": self.result,
            "error": self.error,
            "details": [d.to_dict() for d in (self.details or [])],
        }