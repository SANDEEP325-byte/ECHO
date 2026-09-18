"""Voice Session State Machine (Phase 6A).

Manages the lifecycle and state transitions of an active voice interaction.
Guarantees thread-safe state changes, execution bounds, and fail-closed handling.
"""

import threading
import time
from typing import ClassVar
from uuid import uuid4

from packages.interfaces.voice import VoiceSession, VoiceSessionState
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.voice.errors import VoiceSessionError


class VoiceSessionController:
    """Thread-safe controller for a VoiceSession lifecycle."""

    # Valid state transition mapping
    _ALLOWED_TRANSITIONS: ClassVar[dict[VoiceSessionState, set[VoiceSessionState]]] = {
        VoiceSessionState.IDLE: {
            VoiceSessionState.LISTENING,
            VoiceSessionState.SPEAKING,
            VoiceSessionState.ERROR,
            VoiceSessionState.CLOSED,
        },
        VoiceSessionState.LISTENING: {
            VoiceSessionState.PROCESSING,
            VoiceSessionState.IDLE,
            VoiceSessionState.ERROR,
            VoiceSessionState.CLOSED,
        },
        VoiceSessionState.PROCESSING: {
            VoiceSessionState.SPEAKING,
            VoiceSessionState.COMPLETED,
            VoiceSessionState.ERROR,
            VoiceSessionState.CLOSED,
        },
        VoiceSessionState.SPEAKING: {
            VoiceSessionState.COMPLETED,
            VoiceSessionState.IDLE,
            VoiceSessionState.ERROR,
            VoiceSessionState.CLOSED,
        },
        VoiceSessionState.COMPLETED: {
            VoiceSessionState.IDLE,
            VoiceSessionState.LISTENING,
            VoiceSessionState.SPEAKING,
            VoiceSessionState.CLOSED,
        },
        VoiceSessionState.ERROR: {
            VoiceSessionState.IDLE,
            VoiceSessionState.LISTENING,
            VoiceSessionState.CLOSED,
        },
        VoiceSessionState.CLOSED: {
            VoiceSessionState.IDLE,
        },
    }

    def __init__(
        self,
        session_id: str | None = None,
        max_duration_seconds: float = 15.0,
        silence_threshold_seconds: float = 2.0,
        idle_timeout_seconds: float = 60.0,
    ) -> None:
        self.session = VoiceSession(
            session_id=session_id or str(uuid4()),
            state=VoiceSessionState.IDLE,
            started_at=time.time(),
            max_duration_seconds=min(max_duration_seconds, 30.0),
            silence_threshold_seconds=silence_threshold_seconds,
        )
        self.idle_timeout_seconds = idle_timeout_seconds
        self.last_activity_at = time.time()
        self._lock = threading.RLock()

    @property
    def state(self) -> VoiceSessionState:
        """Get current session state."""
        with self._lock:
            return self.session.state

    @property
    def session_id(self) -> str:
        """Get unique session identifier."""
        return self.session.session_id

    def transition_to(self, new_state: VoiceSessionState, error: str | None = None) -> None:
        """Atomically transition session state, raising VoiceSessionError on illegal changes."""
        with self._lock:
            current = self.session.state
            allowed = self._ALLOWED_TRANSITIONS.get(current, set())
            if new_state not in allowed:
                err_msg = (
                    f"Invalid voice session transition from {current.value} to {new_state.value}."
                )
                logger.error(err_msg)
                self.session.state = VoiceSessionState.ERROR
                self.session.error = err_msg
                raise VoiceSessionError(err_msg)

            logger.info(
                "Voice session %s: %s -> %s", self.session_id, current.value, new_state.value
            )
            self.session.state = new_state
            self.last_activity_at = time.time()
            if error is not None:
                self.session.error = error

    def start_listening(self) -> None:
        """Transition session to LISTENING state."""
        with self._lock:
            self.session.started_at = time.time()
            self.transition_to(VoiceSessionState.LISTENING)

    def start_processing(self) -> None:
        """Transition session to PROCESSING state."""
        with self._lock:
            self.transition_to(VoiceSessionState.PROCESSING)

    def start_speaking(self) -> None:
        """Transition session to SPEAKING state."""
        with self._lock:
            self.transition_to(VoiceSessionState.SPEAKING)

    def complete(self, transcription: str = "") -> None:
        """Transition session to COMPLETED state."""
        with self._lock:
            self.session.transcription = transcription
            self.transition_to(VoiceSessionState.COMPLETED)

    def close(self) -> None:
        """Transition session to CLOSED state."""
        with self._lock:
            self.transition_to(VoiceSessionState.CLOSED)

    def fail(self, error: str) -> None:
        """Transition session to ERROR state."""
        with self._lock:
            self.session.error = error
            self.session.state = VoiceSessionState.ERROR
            self.last_activity_at = time.time()
            logger.warning("Voice session %s failed: %s", self.session_id, error)

    def reset(self) -> None:
        """Reset session to IDLE state."""
        with self._lock:
            self.session.state = VoiceSessionState.IDLE
            self.session.started_at = time.time()
            self.last_activity_at = time.time()
            self.session.error = None
            self.session.transcription = ""

    def is_expired(self) -> bool:
        """Check if session exceeded maximum allowed recording duration."""
        with self._lock:
            return self.session.is_expired()

    def is_idle_timed_out(self) -> bool:
        """Check if session has been inactive past idle timeout."""
        with self._lock:
            return (time.time() - self.last_activity_at) >= self.idle_timeout_seconds
