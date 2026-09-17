from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any
from uuid import uuid4

from packages.interfaces.security import RiskLevel
from packages.interfaces.verification import VerificationResult


class ActionState(str, Enum):
    """Lifecycle states of an action requiring user confirmation."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


class ConfirmationStatus(str, Enum):
    """Structured status codes for action confirmation and cancellation operations."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    ALREADY_PROCESSED = "already_processed"
    INVALID = "invalid"
    FAILED = "failed"
    REQUIRED = "confirmation_required"


@dataclass
class PendingAction:
    """Represents an immutable, validated action awaiting human confirmation."""

    action_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: RiskLevel
    created_at: float
    expires_at: float
    state: ActionState = ActionState.PENDING
    request_id: str | None = None
    step_number: int | None = None
    execution_result: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        # Enforce shallow copy of arguments to prevent external mutation
        if isinstance(self.arguments, dict):
            self.arguments = dict(self.arguments)

    def is_expired(self, current_time: float | None = None) -> bool:
        """Check if action has passed its expiration timestamp."""
        now = current_time if current_time is not None else time.time()
        return now >= self.expires_at

    def is_pending(self) -> bool:
        """Check if action is strictly in PENDING state and not expired."""
        return self.state == ActionState.PENDING and not self.is_expired()

    def to_dict(self) -> dict[str, Any]:
        """Produce safe structured dictionary representation without technical leakage."""
        return {
            "action_id": self.action_id,
            "tool": self.tool_name,
            "step_number": self.step_number,
            "arguments": dict(self.arguments),
            "risk_level": self.risk_level.value if hasattr(self.risk_level, "value") else str(self.risk_level),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "state": self.state.value,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class ConfirmationResult:
    """Structured response contract for confirmation and cancellation operations."""

    success: bool
    status: ConfirmationStatus
    action_id: str | None
    message: str
    result: Any = None
    error: str | None = None
    pending_action: dict[str, Any] | None = None
    verification: VerificationResult | None = None
