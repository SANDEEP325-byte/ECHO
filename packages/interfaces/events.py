"""Real-Time Interface Event Models (Phase 10C.1).

Defines bounded, validated event contracts for the ECHO real-time interface gateway.
Supports state synchronization for future Jarvis-style voice HUD, avatar state machine,
and screen/voice confirmation workflows.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InterfaceEventType(str, Enum):
    """Canonical event types for ECHO interface gateway."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ALERT = "alert"
    ERROR = "error"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ACTION_RESULT = "action_result"


class IdlePayload(BaseModel):
    """Payload when assistant is idle/ready."""

    model_config = ConfigDict(extra="forbid")
    status: str = Field(default="ready", max_length=64)
    message: str = Field(default="ECHO is ready.", max_length=256)


class ListeningPayload(BaseModel):
    """Payload when voice/microphone capture is listening."""

    model_config = ConfigDict(extra="forbid")
    transcript_partial: str = Field(default="", max_length=1024)
    is_final: bool = False


class ThinkingPayload(BaseModel):
    """Payload when ECHOBrain is processing/planning."""

    model_config = ConfigDict(extra="forbid")
    user_input: str = Field(min_length=1, max_length=4096)
    step_description: str | None = Field(default=None, max_length=512)


class SpeakingPayload(BaseModel):
    """Payload when vocalizing or displaying response."""

    model_config = ConfigDict(extra="forbid")
    response_text: str = Field(min_length=1, max_length=16384)
    audio_duration: float | None = Field(default=None, ge=0.0, le=300.0)


class AlertPayload(BaseModel):
    """Payload for system notifications and alerts."""

    model_config = ConfigDict(extra="forbid")
    level: str = Field(default="info", max_length=32)  # info, warning, security
    title: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2048)


class ErrorPayload(BaseModel):
    """Payload for operational errors."""

    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1024)
    details: str | None = Field(default=None, max_length=2048)


class ConfirmationRequiredPayload(BaseModel):
    """Payload when a sensitive action requires human authorization."""

    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)
    risk_level: str = Field(default="SENSITIVE", max_length=32)
    safe_description: str = Field(min_length=1, max_length=1024)
    parameters: dict[str, Any] = Field(default_factory=dict)
    expires_at: float | None = None


class ActionResultPayload(BaseModel):
    """Payload representing outcome of an action confirmation/cancellation."""

    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=64)  # confirmed, cancelled, failed, expired
    success: bool
    message: str = Field(default="", max_length=1024)
    result: Any = None


class InterfaceEvent(BaseModel):
    """Unified envelope for all outbound gateway events."""

    model_config = ConfigDict(extra="forbid")
    event_type: InterfaceEventType
    session_id: str = Field(min_length=1, max_length=128)
    timestamp: float = Field(default_factory=time.time)
    payload: dict[str, Any]


class ClientMessageType(str, Enum):
    """Inbound message types from connected clients."""

    USER_INPUT = "user_input"
    CONFIRM_ACTION = "confirm_action"
    CANCEL_ACTION = "cancel_action"
    PING = "ping"
    STATE_QUERY = "state_query"


class InboundClientMessage(BaseModel):
    """Validated schema for messages sent from client to server."""

    model_config = ConfigDict(extra="forbid")
    action: ClientMessageType
    session_id: str | None = Field(default=None, max_length=128)
    user_input: str | None = Field(default=None, max_length=4096)
    action_id: str | None = Field(default=None, max_length=128)
