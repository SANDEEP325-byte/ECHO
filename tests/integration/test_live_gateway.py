"""Integration tests for ECHO Phase 10C.1: Real-Time Interface Event Gateway.

Verifies:
- WebSocket endpoint /ws/live connection handshake and initial IDLE event
- Custom and generated session_id propagation
- Strict origin validation (allowing localhost/127.0.0.1/null, rejecting external origins)
- Bounded payload enforcement (>64KB rejected)
- Malformed JSON and schema validation error handling
- Inbound user_input dispatch through ECHOBrain (THINKING -> SPEAKING -> IDLE)
- Confirmation flow (CONFIRMATION_REQUIRED -> CONFIRM_ACTION / CANCEL_ACTION -> ACTION_RESULT)
- Parameter sanitization (passwords/tokens/secrets redacted)
- Session isolation (events routed strictly to target session)
- Graceful shutdown via ConnectionManager.close_all()
- Ping/pong heartbeat and state query
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from packages.interfaces.events import (
    ClientMessageType,
    InterfaceEventType,
)
from packages.interfaces.pending_action import ConfirmationResult, ConfirmationStatus
from packages.interfaces.request import Request
from services.api.connection_manager import connection_manager
from services.api.live_gateway import is_origin_allowed, sanitize_action_parameters
from services.api.main import app


def test_is_origin_allowed_validation() -> None:
    """Verify localhost, 127.0.0.1, and empty origins are allowed while external and null are rejected."""
    assert is_origin_allowed(None) is True
    assert is_origin_allowed("") is True
    assert is_origin_allowed("http://localhost") is True
    assert is_origin_allowed("http://localhost:8000") is True
    assert is_origin_allowed("http://localhost:5173") is True
    assert is_origin_allowed("http://127.0.0.1:8000") is True
    assert is_origin_allowed("https://localhost:443") is True

    # "null" origin must be rejected to prevent sandboxed iframe CSWSH attacks
    assert is_origin_allowed("null") is False

    # External / untrusted origins must be rejected
    assert is_origin_allowed("http://evil.com") is False
    assert is_origin_allowed("http://attacker.org:8000") is False
    assert is_origin_allowed("https://malicious-site.net") is False


def test_websocket_connect_handshake_default_session() -> None:
    """Verify clean connection and initial IDLE handshake event with generated session."""
    with TestClient(app) as client, client.websocket_connect("/ws/live") as ws:
        data = ws.receive_json()
        assert data["event_type"] == InterfaceEventType.IDLE.value
        assert data["session_id"].startswith("web_")
        assert data["payload"]["status"] == "ready"


def test_websocket_connect_handshake_explicit_session() -> None:
    """Verify custom session_id query parameter is preserved."""
    custom_session = "user_hud_session_99"
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws/live?session_id={custom_session}") as ws,
    ):
        data = ws.receive_json()
        assert data["event_type"] == InterfaceEventType.IDLE.value
        assert data["session_id"] == custom_session


def test_websocket_rejects_unauthorized_origin() -> None:
    """Verify connection from an untrusted origin is rejected with policy violation."""
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/ws/live",
            headers={"origin": "http://evil-attacker.com"},
        ),
    ):
        pass
    assert exc_info.value.code == 1008


def test_websocket_rejects_null_origin() -> None:
    """Verify connection with Origin: null is rejected with 1008 policy violation."""
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/ws/live",
            headers={"origin": "null"},
        ),
    ):
        pass
    assert exc_info.value.code == 1008


def test_websocket_ping_pong_heartbeat() -> None:
    """Verify client ping action returns pong alert event."""
    with TestClient(app) as client, client.websocket_connect("/ws/live") as ws:
        ws.receive_json()  # Consume initial IDLE

        ws.send_json({"action": ClientMessageType.PING.value})
        resp = ws.receive_json()
        assert resp["event_type"] == InterfaceEventType.ALERT.value
        assert resp["payload"]["title"] == "pong"


def test_websocket_state_query() -> None:
    """Verify client state query returns current IDLE state."""
    with TestClient(app) as client, client.websocket_connect("/ws/live") as ws:
        ws.receive_json()  # Consume initial IDLE

        ws.send_json({"action": ClientMessageType.STATE_QUERY.value})
        resp = ws.receive_json()
        assert resp["event_type"] == InterfaceEventType.IDLE.value


def test_websocket_malformed_json_returns_error() -> None:
    """Verify malformed JSON message receives clean ERROR event without dropping socket."""
    with TestClient(app) as client, client.websocket_connect("/ws/live") as ws:
        ws.receive_json()  # Consume initial IDLE

        ws.send_text("THIS IS NOT JSON {{{")
        resp = ws.receive_json()
        assert resp["event_type"] == InterfaceEventType.ERROR.value
        assert resp["payload"]["code"] == "INVALID_JSON"


def test_websocket_validation_error_invalid_action() -> None:
    """Verify invalid action type triggers VALIDATION_ERROR event."""
    with TestClient(app) as client, client.websocket_connect("/ws/live") as ws:
        ws.receive_json()  # Consume initial IDLE

        ws.send_json({"action": "unsupported_unknown_action"})
        resp = ws.receive_json()
        assert resp["event_type"] == InterfaceEventType.ERROR.value
        assert resp["payload"]["code"] == "VALIDATION_ERROR"


def test_websocket_empty_user_input_rejected() -> None:
    """Verify empty or whitespace-only user input returns EMPTY_INPUT error."""
    with TestClient(app) as client, client.websocket_connect("/ws/live") as ws:
        ws.receive_json()  # Consume initial IDLE

        ws.send_json({"action": ClientMessageType.USER_INPUT.value, "user_input": "   "})
        resp = ws.receive_json()
        assert resp["event_type"] == InterfaceEventType.ERROR.value
        assert resp["payload"]["code"] == "EMPTY_INPUT"


def test_websocket_oversized_payload_rejected() -> None:
    """Verify payloads exceeding 64KB are rejected with PAYLOAD_TOO_LARGE."""
    oversized = "A" * (65536 + 100)
    with TestClient(app) as client, client.websocket_connect("/ws/live") as ws:
        ws.receive_json()  # Consume initial IDLE

        ws.send_text(oversized)
        resp = ws.receive_json()
        assert resp["event_type"] == InterfaceEventType.ERROR.value
        assert resp["payload"]["code"] == "PAYLOAD_TOO_LARGE"


def test_websocket_user_input_dispatch_cycle() -> None:
    """Verify user input triggers THINKING, processes via Brain, then emits SPEAKING and IDLE."""
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/live?session_id=cycle_session") as ws,
    ):
        ws.receive_json()  # Consume initial IDLE

        with patch(
            "services.api.live_gateway.echo_brain.process",
            AsyncMock(return_value="Greetings, commander."),
        ) as mock_process:
            ws.send_json(
                {
                    "action": ClientMessageType.USER_INPUT.value,
                    "user_input": "Status report",
                }
            )

            # 1. Expect THINKING event
            event1 = ws.receive_json()
            assert event1["event_type"] == InterfaceEventType.THINKING.value
            assert event1["payload"]["user_input"] == "Status report"

            # 2. Expect SPEAKING event
            event2 = ws.receive_json()
            assert event2["event_type"] == InterfaceEventType.SPEAKING.value
            assert event2["payload"]["response_text"] == "Greetings, commander."

            # 3. Expect transition back to IDLE
            event3 = ws.receive_json()
            assert event3["event_type"] == InterfaceEventType.IDLE.value

            # Verify Brain received Request with source="web" and session_id="cycle_session"
            mock_process.assert_awaited_once()
            call_arg = mock_process.await_args[0][0]
            assert isinstance(call_arg, Request)
            assert call_arg.source == "web"
            assert call_arg.session_id == "cycle_session"


def test_sanitize_action_parameters_composite_keys() -> None:
    """Verify composite keys containing sensitive substrings are thoroughly redacted."""
    raw_args = {
        "access_token": "eyJhbGciOi...",
        "db_password": "super_secret_pw",
        "client_secret": "sec_999",
        "auth_token": "bearer_abc",
        "custom_api_key": "key_12345",
        "session_cookie": "sess=abcdef",
        "proxy_headers": "Authorization: Bearer xyz",
        "private_key_path": "/path/to/key.pem",
        "database_name": "production_users",
        "port": 5432,
        "is_active": True,
        "tags": ["finance", "backup"],
    }
    sanitized = sanitize_action_parameters(raw_args)

    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["db_password"] == "[REDACTED]"
    assert sanitized["client_secret"] == "[REDACTED]"
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["custom_api_key"] == "[REDACTED]"
    assert sanitized["session_cookie"] == "[REDACTED]"
    assert sanitized["proxy_headers"] == "[REDACTED]"
    assert sanitized["private_key_path"] == "[REDACTED]"

    # Non-sensitive keys remain intact
    assert sanitized["database_name"] == "production_users"
    assert sanitized["port"] == 5432
    assert sanitized["is_active"] is True
    assert sanitized["tags"] == ["finance", "backup"]


def test_websocket_confirmation_required_flow_and_redaction() -> None:
    """Verify sensitive action emits CONFIRMATION_REQUIRED with redacted composite secrets, then confirms."""
    raw_secret = "secret_password_12345"

    async def fake_brain_process_confirm(req: Request) -> str:
        req.context["requires_confirmation"] = True
        req.context["pending_action_id"] = "act_gateway_77"
        req.result = MagicMock()
        req.result.requires_confirmation = True
        req.result.pending_action = {
            "action_id": "act_gateway_77",
            "tool": "delete_database",
            "risk_level": "CRITICAL",
            "arguments": {
                "db_password": raw_secret,
                "access_token": "api_token_abc",
                "client_secret": "my_secret_key",
                "auth_token": "bearer_token_xyz",
                "database_name": "prod_backup",
            },
        }
        return "Action requires human approval."

    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/live?session_id=confirm_session") as ws,
    ):
        ws.receive_json()  # Consume initial IDLE

        with (
            patch(
                "services.api.live_gateway.echo_brain.process",
                fake_brain_process_confirm,
            ),
            patch(
                "services.api.live_gateway.echo_brain.confirm_action",
                MagicMock(
                    return_value=ConfirmationResult(
                        success=True,
                        status=ConfirmationStatus.CONFIRMED,
                        action_id="act_gateway_77",
                        message="Database deleted successfully.",
                        result="Done.",
                    )
                ),
            ) as mock_confirm,
        ):
            # 1. Trigger request requiring confirmation
            ws.send_json(
                {
                    "action": ClientMessageType.USER_INPUT.value,
                    "user_input": "delete database",
                }
            )

            # Expect THINKING
            ws.receive_json()

            # Expect CONFIRMATION_REQUIRED
            conf_event = ws.receive_json()
            assert conf_event["event_type"] == InterfaceEventType.CONFIRMATION_REQUIRED.value
            payload = conf_event["payload"]
            assert payload["action_id"] == "act_gateway_77"
            assert payload["tool_name"] == "delete_database"
            assert payload["risk_level"] == "CRITICAL"

            # Verify composite secrets are redacted
            raw_json = json.dumps(payload)
            assert raw_secret not in raw_json
            assert "api_token_abc" not in raw_json
            assert "my_secret_key" not in raw_json
            assert "bearer_token_xyz" not in raw_json
            assert payload["parameters"]["db_password"] == "[REDACTED]"
            assert payload["parameters"]["access_token"] == "[REDACTED]"
            assert payload["parameters"]["client_secret"] == "[REDACTED]"
            assert payload["parameters"]["auth_token"] == "[REDACTED]"
            assert payload["parameters"]["database_name"] == "prod_backup"

            # 2. Client sends CONFIRM_ACTION
            ws.send_json(
                {
                    "action": ClientMessageType.CONFIRM_ACTION.value,
                    "action_id": "act_gateway_77",
                }
            )

            # Expect ACTION_RESULT
            res_event = ws.receive_json()
            assert res_event["event_type"] == InterfaceEventType.ACTION_RESULT.value
            assert res_event["payload"]["status"] == "confirmed"
            assert res_event["payload"]["success"] is True

            # Expect IDLE
            ws.receive_json()

            # Verify authoritative confirmation API called
            mock_confirm.assert_called_once_with("act_gateway_77", session_id="confirm_session")


def test_websocket_action_cancellation_flow() -> None:
    """Verify client CANCEL_ACTION delegates to brain.cancel_action and returns ACTION_RESULT."""
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/live?session_id=cancel_session") as ws,
    ):
        ws.receive_json()  # Consume initial IDLE

        with patch(
            "services.api.live_gateway.echo_brain.cancel_action",
            MagicMock(
                return_value=ConfirmationResult(
                    success=True,
                    status=ConfirmationStatus.CANCELLED,
                    action_id="act_to_cancel_88",
                    message="Action cancelled.",
                )
            ),
        ) as mock_cancel:
            ws.send_json(
                {
                    "action": ClientMessageType.CANCEL_ACTION.value,
                    "action_id": "act_to_cancel_88",
                }
            )

            res_event = ws.receive_json()
            assert res_event["event_type"] == InterfaceEventType.ACTION_RESULT.value
            assert res_event["payload"]["status"] == "cancelled"
            assert res_event["payload"]["success"] is True

            # Expect transition to IDLE
            ws.receive_json()

            mock_cancel.assert_called_once_with("act_to_cancel_88", session_id="cancel_session")


def test_websocket_confirm_action_missing_id() -> None:
    """Verify confirm_action without action_id returns MISSING_ACTION_ID error."""
    with TestClient(app) as client, client.websocket_connect("/ws/live") as ws:
        ws.receive_json()  # Consume initial IDLE

        ws.send_json({"action": ClientMessageType.CONFIRM_ACTION.value, "action_id": ""})
        res_event = ws.receive_json()
        assert res_event["event_type"] == InterfaceEventType.ERROR.value
        assert res_event["payload"]["code"] == "MISSING_ACTION_ID"


def test_websocket_session_isolation() -> None:
    """Verify messages and events in Session A do not leak into Session B."""
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/live?session_id=session_A") as ws_a,
        client.websocket_connect("/ws/live?session_id=session_B") as ws_b,
    ):
        # Consume initial IDLEs
        init_a = ws_a.receive_json()
        init_b = ws_b.receive_json()
        assert init_a["session_id"] == "session_A"
        assert init_b["session_id"] == "session_B"

        # Send message on Session A
        with patch(
            "services.api.live_gateway.echo_brain.process",
            AsyncMock(return_value="Only for session A"),
        ):
            ws_a.send_json(
                {
                    "action": ClientMessageType.USER_INPUT.value,
                    "user_input": "Ping session A",
                }
            )

            # ws_a receives THINKING, SPEAKING, IDLE
            event1 = ws_a.receive_json()
            assert event1["session_id"] == "session_A"
            event2 = ws_a.receive_json()
            assert event2["payload"]["response_text"] == "Only for session A"
            event3 = ws_a.receive_json()
            assert event3["event_type"] == InterfaceEventType.IDLE.value

            # ws_b should be idle, send ping on B and verify B only gets B's pong
            ws_b.send_json({"action": ClientMessageType.PING.value})
            event_b = ws_b.receive_json()
            assert event_b["session_id"] == "session_B"
            assert event_b["payload"]["title"] == "pong"


@pytest.mark.anyio
async def test_connection_manager_clean_shutdown() -> None:
    """Verify ConnectionManager.close_all closes active sockets cleanly."""
    mock_ws = AsyncMock()
    await connection_manager.connect(mock_ws, "test_shutdown_session")
    assert connection_manager.get_connection_count("test_shutdown_session") == 1

    await connection_manager.close_all(code=1001, reason="Test shutdown")
    mock_ws.close.assert_awaited_once_with(code=1001, reason="Test shutdown")
    assert connection_manager.get_connection_count() == 0
