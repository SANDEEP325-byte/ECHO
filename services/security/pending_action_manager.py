import threading
import time
from typing import Any
from uuid import uuid4

from packages.interfaces.pending_action import (
    ActionState,
    ConfirmationResult,
    ConfirmationStatus,
    PendingAction,
)
from packages.interfaces.security import RiskLevel
from services.logging.logger import logger


class PendingActionManager:
    """Thread-safe, in-memory lifecycle manager for actions requiring human confirmation."""

    DEFAULT_TTL_SECONDS = 300.0  # 5 minutes
    MAX_STORED_ACTIONS = 200

    def __init__(
        self,
        default_ttl: float = DEFAULT_TTL_SECONDS,
        max_stored_actions: int = MAX_STORED_ACTIONS,
    ) -> None:
        self.default_ttl = default_ttl
        self.max_stored_actions = max_stored_actions
        self._actions: dict[str, PendingAction] = {}
        self._lock = threading.RLock()

    def create_pending_action(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: RiskLevel,
        request_id: str | None = None,
        step_number: int | None = None,
        ttl_seconds: float | None = None,
    ) -> PendingAction:
        """Create and store an immutable pending action bound to validated parameters."""
        with self._lock:
            self._prune_if_needed()

            action_id = str(uuid4())
            now = time.time()
            ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else self.default_ttl
            expires_at = now + ttl

            action = PendingAction(
                action_id=action_id,
                tool_name=tool_name,
                arguments=arguments,
                risk_level=risk_level,
                created_at=now,
                expires_at=expires_at,
                state=ActionState.PENDING,
                request_id=request_id,
                step_number=step_number,
            )

            self._actions[action_id] = action

            logger.info(
                "Created pending action: id={}, tool={}, risk={}, ttl={}s",
                action_id,
                tool_name,
                risk_level.value if hasattr(risk_level, "value") else risk_level,
                ttl,
            )

            return action

    def get_action(self, action_id: str) -> PendingAction | None:
        """Retrieve a pending action by its unique ID, transitioning state to EXPIRED if overdue."""
        if not action_id or not isinstance(action_id, str):
            return None

        with self._lock:
            action = self._actions.get(action_id)
            if action is None:
                return None

            if action.state == ActionState.PENDING and action.is_expired():
                action.state = ActionState.EXPIRED
                logger.info("Pending action {} has expired", action_id)

            return action

    def claim_for_execution(
        self,
        action_id: str,
    ) -> tuple[bool, PendingAction | None, ConfirmationStatus, str]:
        """Atomically claim a pending action for execution.
        
        Guarantees single-use execution: transitions state PENDING -> CONFIRMED under lock.
        Prevents replay, double-confirmation, and duplicate concurrent execution.
        """
        if not action_id or not isinstance(action_id, str):
            return False, None, ConfirmationStatus.INVALID, "Invalid action identifier."

        with self._lock:
            action = self._actions.get(action_id)
            if action is None:
                return False, None, ConfirmationStatus.NOT_FOUND, "No pending action found with the specified identifier."

            if action.state == ActionState.PENDING and action.is_expired():
                action.state = ActionState.EXPIRED
                return False, action, ConfirmationStatus.EXPIRED, "The pending action has expired and cannot be executed."

            if action.state != ActionState.PENDING:
                return (
                    False,
                    action,
                    ConfirmationStatus.ALREADY_PROCESSED,
                    f"The pending action has already been processed (state: {action.state.value}).",
                )

            # Atomic transition to CONFIRMED prevents any concurrent thread from claiming
            action.state = ActionState.CONFIRMED
            logger.info("Pending action {} atomically claimed for execution", action_id)
            return True, action, ConfirmationStatus.CONFIRMED, "Action successfully claimed for execution."

    def mark_executed(self, action_id: str, result: Any = None) -> None:
        """Mark an action as successfully executed."""
        with self._lock:
            action = self._actions.get(action_id)
            if action:
                action.state = ActionState.EXECUTED
                action.execution_result = result
                logger.info("Pending action {} marked as EXECUTED", action_id)

    def mark_failed(self, action_id: str, error: str) -> None:
        """Mark an action as failed during execution."""
        with self._lock:
            action = self._actions.get(action_id)
            if action:
                action.state = ActionState.FAILED
                action.error = error
                logger.warning("Pending action {} marked as FAILED: {}", action_id, error)

    def cancel_action(self, action_id: str) -> ConfirmationResult:
        """Idempotently cancel a pending action, permanently preventing execution."""
        if not action_id or not isinstance(action_id, str):
            return ConfirmationResult(
                success=False,
                status=ConfirmationStatus.INVALID,
                action_id=action_id,
                message="Invalid action identifier.",
            )

        with self._lock:
            action = self._actions.get(action_id)
            if action is None:
                return ConfirmationResult(
                    success=False,
                    status=ConfirmationStatus.NOT_FOUND,
                    action_id=action_id,
                    message="No pending action found with the specified identifier.",
                )

            if action.state == ActionState.CANCELLED:
                return ConfirmationResult(
                    success=True,
                    status=ConfirmationStatus.CANCELLED,
                    action_id=action_id,
                    message="Pending action was already cancelled.",
                    pending_action=action.to_dict(),
                )

            if action.state in (ActionState.EXECUTED, ActionState.CONFIRMED):
                return ConfirmationResult(
                    success=False,
                    status=ConfirmationStatus.ALREADY_PROCESSED,
                    action_id=action_id,
                    message=f"Action has already been {action.state.value} and cannot be cancelled.",
                    pending_action=action.to_dict(),
                )

            if action.state == ActionState.PENDING and action.is_expired():
                action.state = ActionState.EXPIRED
                return ConfirmationResult(
                    success=False,
                    status=ConfirmationStatus.EXPIRED,
                    action_id=action_id,
                    message="Pending action has already expired.",
                    pending_action=action.to_dict(),
                )

            action.state = ActionState.CANCELLED
            logger.info("Pending action {} cancelled", action_id)

            return ConfirmationResult(
                success=True,
                status=ConfirmationStatus.CANCELLED,
                action_id=action_id,
                message="Pending action successfully cancelled.",
                pending_action=action.to_dict(),
            )

    def _prune_if_needed(self) -> None:
        """Prune expired and completed actions if capacity threshold is exceeded."""
        now = time.time()
        # First expire overdue pending actions
        for act in self._actions.values():
            if act.state == ActionState.PENDING and act.is_expired(now):
                act.state = ActionState.EXPIRED

        if len(self._actions) >= self.max_stored_actions:
            # Remove non-pending actions first
            to_remove = [
                aid for aid, act in self._actions.items()
                if act.state in (ActionState.EXPIRED, ActionState.CANCELLED, ActionState.EXECUTED, ActionState.FAILED)
            ]
            for aid in to_remove:
                del self._actions[aid]

            # If still over limit, drop oldest
            if len(self._actions) >= self.max_stored_actions:
                sorted_actions = sorted(self._actions.items(), key=lambda item: item[1].created_at)
                excess = len(self._actions) - self.max_stored_actions + 1
                for aid, _ in sorted_actions[:excess]:
                    del self._actions[aid]

    def clear(self) -> None:
        """Clear all stored actions (primarily for test isolation)."""
        with self._lock:
            self._actions.clear()


pending_action_manager = PendingActionManager()
