"""Real-Time Interface Event Gateway (Phase 10C.1).

Provides local-only WebSocket endpoint (/ws/live) connecting the future
Jarvis-style command center and avatar to ECHO's cognitive pipeline.

Architectural and Security Rules:
- Binds and accepts connections strictly from local origins (localhost, 127.0.0.1).
- Dispatches all conversational input through Request(source="web") -> ECHOBrain.process().
- Never directly executes tools, bypassing SafetyEngine or ExecutionEngine.
- Action confirmation routes strictly through authoritative ECHOBrain.confirm_action()
  and ECHOBrain.cancel_action().
- Redacts sensitive parameters from confirmation payloads.
- Bounded payload sizes (max 64KB per frame).
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from packages.interfaces.events import (
    ActionResultPayload,
    AlertPayload,
    ClientMessageType,
    ConfirmationRequiredPayload,
    ErrorPayload,
    IdlePayload,
    InboundClientMessage,
    InterfaceEvent,
    InterfaceEventType,
    SpeakingPayload,
    ThinkingPayload,
)
from packages.interfaces.request import Request
from services.api.connection_manager import connection_manager
from services.brain.brain import echo_brain
from services.logging.logger import logger  # type: ignore[attr-defined]

live_router = APIRouter()

MAX_MESSAGE_BYTES = 65536  # 64 KB maximum payload limit

SENSITIVE_PARAM_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "credential",
        "credentials",
        "private_key",
        "cookie",
        "headers",
    }
)


def is_origin_allowed(origin: str | None) -> bool:
    """Verify that WebSocket origin is strictly localhost/local."""
    if origin is None or origin == "":
        return True  # Direct connection (CLI, test client, native wrapper)

    if origin in (
        "http://localhost",
        "http://127.0.0.1",
        "https://localhost",
        "https://127.0.0.1",
    ):
        return True

    try:
        parsed = urlparse(origin)
        hostname = (parsed.hostname or "").lower()
        if hostname in ("localhost", "127.0.0.1"):
            return True
    except Exception:  # noqa: BLE001
        return False

    return False


def sanitize_action_parameters(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Redact sensitive keys from action parameters before sending to client."""
    if not arguments:
        return {}

    sanitized: dict[str, Any] = {}
    for key, val in arguments.items():
        key_lower = key.lower()
        if any(sensitive in key_lower for sensitive in SENSITIVE_PARAM_KEYS):
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = (
                str(val) if not isinstance(val, (int, float, bool, list, dict)) else val
            )

    return sanitized


@live_router.websocket("/ws/live")
async def live_websocket_endpoint(
    websocket: WebSocket,
    session_id: str | None = None,
) -> None:
    """Local real-time event gateway endpoint for ECHO command center."""
    origin = websocket.headers.get("origin")
    if not is_origin_allowed(origin):
        logger.warning("Rejected WebSocket connection from unauthorized origin: {}", origin)
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Unauthorized origin: only localhost connections allowed.",
        )
        return

    # Accept connection and initialize session
    await websocket.accept()
    active_session_id = session_id or f"web_{uuid.uuid4().hex[:8]}"
    await connection_manager.connect(websocket, active_session_id)

    # Emit initial IDLE event to establish handshake and report assigned session ID
    initial_event = InterfaceEvent(
        event_type=InterfaceEventType.IDLE,
        session_id=active_session_id,
        payload=IdlePayload(status="ready", message="ECHO live gateway connected.").model_dump(),
    )
    await websocket.send_json(initial_event.model_dump())

    try:
        while True:
            raw_text = await websocket.receive_text()

            # 1. Enforce payload size limit
            if len(raw_text.encode("utf-8")) > MAX_MESSAGE_BYTES:
                err_event = InterfaceEvent(
                    event_type=InterfaceEventType.ERROR,
                    session_id=active_session_id,
                    payload=ErrorPayload(
                        code="PAYLOAD_TOO_LARGE",
                        message=f"Payload exceeds maximum bound of {MAX_MESSAGE_BYTES} bytes.",
                    ).model_dump(),
                )
                await websocket.send_json(err_event.model_dump())
                continue

            # 2. Parse JSON
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                err_event = InterfaceEvent(
                    event_type=InterfaceEventType.ERROR,
                    session_id=active_session_id,
                    payload=ErrorPayload(
                        code="INVALID_JSON",
                        message="Malformed JSON message format.",
                        details=str(exc),
                    ).model_dump(),
                )
                await websocket.send_json(err_event.model_dump())
                continue

            # 3. Validate against schema
            try:
                client_msg = InboundClientMessage.model_validate(data)
            except ValidationError as val_err:
                err_event = InterfaceEvent(
                    event_type=InterfaceEventType.ERROR,
                    session_id=active_session_id,
                    payload=ErrorPayload(
                        code="VALIDATION_ERROR",
                        message="Invalid message structure.",
                        details=str(val_err),
                    ).model_dump(),
                )
                await websocket.send_json(err_event.model_dump())
                continue

            # 4. Route Message Action
            await handle_client_message(client_msg, websocket, active_session_id)

    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, active_session_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error on WebSocket session {}: {}", active_session_id, exc)
        await connection_manager.disconnect(websocket, active_session_id)


async def handle_client_message(
    msg: InboundClientMessage,
    websocket: WebSocket,
    session_id: str,
) -> None:
    """Process a validated inbound client message."""
    if msg.action == ClientMessageType.PING:
        pong_event = InterfaceEvent(
            event_type=InterfaceEventType.ALERT,
            session_id=session_id,
            payload=AlertPayload(
                level="info",
                title="pong",
                message="ECHO gateway heartbeat confirmed.",
            ).model_dump(),
        )
        await websocket.send_json(pong_event.model_dump())
        return

    if msg.action == ClientMessageType.STATE_QUERY:
        state_event = InterfaceEvent(
            event_type=InterfaceEventType.IDLE,
            session_id=session_id,
            payload=IdlePayload().model_dump(),
        )
        await websocket.send_json(state_event.model_dump())
        return

    if msg.action == ClientMessageType.USER_INPUT:
        user_text = (msg.user_input or "").strip()
        if not user_text:
            err_event = InterfaceEvent(
                event_type=InterfaceEventType.ERROR,
                session_id=session_id,
                payload=ErrorPayload(
                    code="EMPTY_INPUT",
                    message="User input must not be empty.",
                ).model_dump(),
            )
            await websocket.send_json(err_event.model_dump())
            return

        # Notify UI that processing/thinking has begun
        thinking_event = InterfaceEvent(
            event_type=InterfaceEventType.THINKING,
            session_id=session_id,
            payload=ThinkingPayload(user_input=user_text).model_dump(),
        )
        await connection_manager.send_event(session_id, thinking_event)

        # Dispatch through canonical Request -> ECHOBrain.process()
        req = Request(
            user_input=user_text,
            source="web",
            session_id=session_id,
        )

        try:
            response_text = await echo_brain.process(req)
        except Exception as exc:  # noqa: BLE001
            logger.error("Brain execution failed on WebSocket request: {}", exc)
            err_event = InterfaceEvent(
                event_type=InterfaceEventType.ERROR,
                session_id=session_id,
                payload=ErrorPayload(
                    code="BRAIN_PROCESSING_FAILED",
                    message="An internal component failed while processing your request.",
                ).model_dump(),
            )
            await connection_manager.send_event(session_id, err_event)
            return

        # Check if the execution paused for human authorization
        requires_confirm = bool(
            req.context.get("requires_confirmation")
            or (
                hasattr(req, "result")
                and req.result
                and getattr(req.result, "requires_confirmation", False)
            )
        )

        if requires_confirm:
            pending_id = req.context.get("pending_action_id")
            pending_act = (
                getattr(req.result, "pending_action", None) if hasattr(req, "result") else None
            )
            if not pending_id and isinstance(pending_act, dict):
                pending_id = pending_act.get("action_id")

            tool_name = (
                pending_act.get("tool", "Action") if isinstance(pending_act, dict) else "Operation"
            )
            risk_level = (
                str(pending_act.get("risk_level", "SENSITIVE"))
                if isinstance(pending_act, dict)
                else "SENSITIVE"
            )
            raw_args = pending_act.get("arguments", {}) if isinstance(pending_act, dict) else {}
            sanitized_args = sanitize_action_parameters(raw_args)

            confirm_event = InterfaceEvent(
                event_type=InterfaceEventType.CONFIRMATION_REQUIRED,
                session_id=session_id,
                payload=ConfirmationRequiredPayload(
                    action_id=pending_id or "pending",
                    tool_name=tool_name,
                    risk_level=risk_level,
                    safe_description=response_text,
                    parameters=sanitized_args,
                ).model_dump(),
            )
            await connection_manager.send_event(session_id, confirm_event)
        else:
            # Emit speaking response
            speaking_event = InterfaceEvent(
                event_type=InterfaceEventType.SPEAKING,
                session_id=session_id,
                payload=SpeakingPayload(response_text=response_text).model_dump(),
            )
            await connection_manager.send_event(session_id, speaking_event)

            # Return to idle
            idle_event = InterfaceEvent(
                event_type=InterfaceEventType.IDLE,
                session_id=session_id,
                payload=IdlePayload().model_dump(),
            )
            await connection_manager.send_event(session_id, idle_event)
        return

    if msg.action == ClientMessageType.CONFIRM_ACTION:
        action_id = (msg.action_id or "").strip()
        if not action_id:
            err_event = InterfaceEvent(
                event_type=InterfaceEventType.ERROR,
                session_id=session_id,
                payload=ErrorPayload(
                    code="MISSING_ACTION_ID",
                    message="action_id is required to confirm an action.",
                ).model_dump(),
            )
            await websocket.send_json(err_event.model_dump())
            return

        # Delegate strictly to authoritative ECHOBrain confirmation API
        res = echo_brain.confirm_action(action_id, session_id=session_id)
        result_event = InterfaceEvent(
            event_type=InterfaceEventType.ACTION_RESULT,
            session_id=session_id,
            payload=ActionResultPayload(
                action_id=action_id,
                status=res.status.value,
                success=res.success,
                message=res.message,
                result=res.result,
            ).model_dump(),
        )
        await connection_manager.send_event(session_id, result_event)

        # Return to idle
        await connection_manager.send_event(
            session_id,
            InterfaceEvent(
                event_type=InterfaceEventType.IDLE,
                session_id=session_id,
                payload=IdlePayload().model_dump(),
            ),
        )
        return

    if msg.action == ClientMessageType.CANCEL_ACTION:
        action_id = (msg.action_id or "").strip()
        if not action_id:
            err_event = InterfaceEvent(
                event_type=InterfaceEventType.ERROR,
                session_id=session_id,
                payload=ErrorPayload(
                    code="MISSING_ACTION_ID",
                    message="action_id is required to cancel an action.",
                ).model_dump(),
            )
            await websocket.send_json(err_event.model_dump())
            return

        # Delegate strictly to authoritative ECHOBrain cancellation API
        res = echo_brain.cancel_action(action_id, session_id=session_id)
        result_event = InterfaceEvent(
            event_type=InterfaceEventType.ACTION_RESULT,
            session_id=session_id,
            payload=ActionResultPayload(
                action_id=action_id,
                status=res.status.value,
                success=res.success,
                message=res.message,
                result=res.result,
            ).model_dump(),
        )
        await connection_manager.send_event(session_id, result_event)

        # Return to idle
        await connection_manager.send_event(
            session_id,
            InterfaceEvent(
                event_type=InterfaceEventType.IDLE,
                session_id=session_id,
                payload=IdlePayload().model_dump(),
            ),
        )
        return
