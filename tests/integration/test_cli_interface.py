"""Integration tests for ECHO Phase 10B: Interactive Rich CLI Interface.

Verifies:
- Conversational loop and session ID preservation
- Empty input handling
- Slash commands (/help, /status, /memory, /confirm, /cancel, /exit, /quit)
- Confirmation card rendering, strict approval, and strict cancellation
- Graceful termination on Ctrl+C (KeyboardInterrupt) and EOF
- Usability when Ollama is unavailable
- Zero secret or raw tool payload leakage
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from apps.cli.app import CLIApp
from packages.interfaces.pending_action import ConfirmationResult, ConfirmationStatus
from packages.interfaces.request import Request
from services.brain.brain import ECHOBrain
from services.configuration.diagnostics import ComponentStatus, DiagnosticCheck, SystemHealth


def make_scripted_input(inputs: list[str]) -> Callable[[str], str]:
    """Create a deterministic input callable from a sequence of strings."""
    iterator = iter(inputs)

    def _input(prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return _input


@pytest.mark.anyio
async def test_cli_basic_conversation(fresh_echo_brain: ECHOBrain) -> None:
    """Verify basic interactive turn through CLIApp and ECHOBrain."""
    console = Console(record=True, width=120)
    input_fn = make_scripted_input(["Hello", "/exit"])

    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "ECHO" in output
    assert "personal AI assistant" in output or "hello" in output.lower()
    assert "Exiting ECHO... Goodbye!" in output


@pytest.mark.anyio
async def test_cli_session_id_propagation(fresh_echo_brain: ECHOBrain) -> None:
    """Verify session ID is created and preserved across consecutive conversational turns."""
    console = Console(record=True, width=120)
    captured_requests: list[Request] = []
    original_process = fresh_echo_brain.process

    async def capturing_process(req: Request) -> str:
        captured_requests.append(req)
        return await original_process(req)

    fresh_echo_brain.process = capturing_process  # type: ignore[assignment]

    input_fn = make_scripted_input(["My name is Sam", "What is my name?", "/exit"])
    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    assert len(captured_requests) == 2
    req1, req2 = captured_requests
    assert req1.session_id == app.session_id
    assert req2.session_id == app.session_id
    assert req1.source == "cli"
    assert req2.source == "cli"


@pytest.mark.anyio
async def test_cli_empty_input_no_request(fresh_echo_brain: ECHOBrain) -> None:
    """Verify empty or whitespace-only inputs do not trigger Brain processing."""
    console = Console(record=True, width=120)
    mock_process = AsyncMock(return_value="Echo reply")
    fresh_echo_brain.process = mock_process  # type: ignore[assignment]

    input_fn = make_scripted_input(["", "   ", "\t", "/quit"])
    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    assert mock_process.call_count == 0
    assert "Exiting ECHO... Goodbye!" in console.export_text()


@pytest.mark.anyio
async def test_cli_slash_help(fresh_echo_brain: ECHOBrain) -> None:
    """Verify /help displays the command reference table."""
    console = Console(record=True, width=120)
    input_fn = make_scripted_input(["/help", "/exit"])

    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "Available ECHO Commands" in output
    assert "/help" in output
    assert "/status" in output
    assert "/memory" in output
    assert "/confirm" in output
    assert "/cancel" in output
    assert "/exit" in output


@pytest.mark.anyio
async def test_cli_slash_status(fresh_echo_brain: ECHOBrain) -> None:
    """Verify /status renders the diagnostic subsystem status table."""
    console = Console(record=True, width=120)
    input_fn = make_scripted_input(["/status", "/exit"])

    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "Subsystem" in output
    assert "Type" in output
    assert "Status" in output
    assert "Python Runtime" in output


@pytest.mark.anyio
async def test_cli_slash_memory(fresh_echo_brain: ECHOBrain) -> None:
    """Verify /memory displays stored facts and message history safely."""
    console = Console(record=True, width=120)
    assert fresh_echo_brain.memory_manager is not None
    fresh_echo_brain.memory_manager.save_fact("city", "Bangalore")

    input_fn = make_scripted_input(["/memory", "/exit"])
    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "Stored Facts" in output
    assert "city" in output
    assert "Bangalore" in output


@pytest.mark.anyio
async def test_cli_invalid_slash_command(fresh_echo_brain: ECHOBrain) -> None:
    """Verify invalid slash commands produce clear guidance without crashing."""
    console = Console(record=True, width=120)
    input_fn = make_scripted_input(["/invalid_cmd", "/exit"])

    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "Unknown command '/invalid_cmd'" in output
    assert "/help" in output


@pytest.mark.anyio
async def test_cli_clean_exit_on_keyboard_interrupt(fresh_echo_brain: ECHOBrain) -> None:
    """Verify Ctrl+C (KeyboardInterrupt) exits cleanly without printing a traceback."""
    console = Console(record=True, width=120)

    def interrupting_input(prompt: str) -> str:
        raise KeyboardInterrupt

    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=interrupting_input)
    await app.run()

    output = console.export_text()
    assert "Exiting ECHO... Goodbye!" in output
    assert "Traceback" not in output


@pytest.mark.anyio
async def test_cli_clean_exit_on_eof(fresh_echo_brain: ECHOBrain) -> None:
    """Verify EOF terminates the CLI cleanly without printing a traceback."""
    console = Console(record=True, width=120)

    def eof_input(prompt: str) -> str:
        raise EOFError

    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=eof_input)
    await app.run()

    output = console.export_text()
    assert "Exiting ECHO... Goodbye!" in output
    assert "Traceback" not in output


@pytest.mark.anyio
async def test_cli_confirmation_approval_flow(fresh_echo_brain: ECHOBrain) -> None:
    """Verify human-in-the-loop confirmation card rendering and strict approval."""
    console = Console(record=True, width=120)

    # Simulate an initial turn that returns a confirmation-required response
    pending_action_data = {
        "action_id": "act_test_123",
        "tool": "delete_file",
        "risk_level": "CRITICAL",
        "arguments": {"path": "C:\\safe\\test.txt"},
    }

    async def fake_confirm_process(req: Request) -> str:
        req.context["requires_confirmation"] = True
        req.context["pending_action_id"] = "act_test_123"
        req.result = MagicMock()
        req.result.requires_confirmation = True
        req.result.pending_action = pending_action_data
        return "This action requires authorization to proceed."

    fresh_echo_brain.process = fake_confirm_process  # type: ignore[assignment]
    fresh_echo_brain.confirm_action = MagicMock(  # type: ignore[assignment]
        return_value=ConfirmationResult(
            success=True,
            status=ConfirmationStatus.CONFIRMED,
            action_id="act_test_123",
            message="Operation completed successfully.",
            result="File deleted.",
        )
    )

    # Sequence: 1. trigger sensitive operation, 2. approve with 'yes', 3. exit
    input_fn = make_scripted_input(["delete test file", "yes", "/exit"])
    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "Confirmation Required" in output
    assert "delete_file" in output
    assert "act_test_123" in output
    assert "confirmed and executed successfully" in output
    fresh_echo_brain.confirm_action.assert_called_once_with(
        "act_test_123", session_id=app.session_id
    )


@pytest.mark.anyio
async def test_cli_confirmation_rejection_flow(fresh_echo_brain: ECHOBrain) -> None:
    """Verify human-in-the-loop confirmation cancellation via 'no'."""
    console = Console(record=True, width=120)

    pending_action_data = {
        "action_id": "act_cancel_456",
        "tool": "terminal_exec",
        "risk_level": "SENSITIVE",
        "arguments": {"command": "npm test"},
    }

    async def fake_confirm_process(req: Request) -> str:
        req.context["requires_confirmation"] = True
        req.context["pending_action_id"] = "act_cancel_456"
        req.result = MagicMock()
        req.result.requires_confirmation = True
        req.result.pending_action = pending_action_data
        return "Action requires approval."

    fresh_echo_brain.process = fake_confirm_process  # type: ignore[assignment]
    fresh_echo_brain.cancel_action = MagicMock(  # type: ignore[assignment]
        return_value=ConfirmationResult(
            success=True,
            status=ConfirmationStatus.CANCELLED,
            action_id="act_cancel_456",
            message="Action cancelled.",
        )
    )

    input_fn = make_scripted_input(["run sensitive script", "no", "/exit"])
    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "Confirmation Required" in output
    assert "act_cancel_456" in output
    assert "has been cancelled" in output
    fresh_echo_brain.cancel_action.assert_called_once_with(
        "act_cancel_456", session_id=app.session_id
    )


@pytest.mark.anyio
async def test_cli_confirmation_strict_non_fuzzy_input(fresh_echo_brain: ECHOBrain) -> None:
    """Verify ambiguous non-confirmation input is rejected while action is pending."""
    console = Console(record=True, width=120)

    pending_action_data = {
        "action_id": "act_strict_789",
        "tool": "delete_file",
        "risk_level": "CRITICAL",
        "arguments": {},
    }

    async def fake_confirm_process(req: Request) -> str:
        req.context["requires_confirmation"] = True
        req.context["pending_action_id"] = "act_strict_789"
        req.result = MagicMock()
        req.result.requires_confirmation = True
        req.result.pending_action = pending_action_data
        return "Pending authorization."

    fresh_echo_brain.process = fake_confirm_process  # type: ignore[assignment]

    # Fuzzy/unclear responses: "maybe", "why?" must be rejected; then cancel
    input_fn = make_scripted_input(["delete file", "maybe later", "cancel", "/exit"])
    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "is pending authorization. Please respond strictly with 'yes' to approve" in output


@pytest.mark.anyio
async def test_cli_slash_confirm_and_cancel_explicit_id(fresh_echo_brain: ECHOBrain) -> None:
    """Verify /confirm <id> and /cancel <id> invoke authoritative Brain APIs directly."""
    console = Console(record=True, width=120)

    fresh_echo_brain.confirm_action = MagicMock(  # type: ignore[assignment]
        return_value=ConfirmationResult(
            success=True,
            status=ConfirmationStatus.CONFIRMED,
            action_id="act_explicit_1",
            message="Confirmed.",
            result="Success.",
        )
    )
    fresh_echo_brain.cancel_action = MagicMock(  # type: ignore[assignment]
        return_value=ConfirmationResult(
            success=True,
            status=ConfirmationStatus.CANCELLED,
            action_id="act_explicit_2",
            message="Cancelled.",
        )
    )

    input_fn = make_scripted_input(["/confirm act_explicit_1", "/cancel act_explicit_2", "/exit"])
    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    assert "act_explicit_1" in output
    assert "act_explicit_2" in output
    fresh_echo_brain.confirm_action.assert_called_once_with(
        "act_explicit_1", session_id=app.session_id
    )
    fresh_echo_brain.cancel_action.assert_called_once_with(
        "act_explicit_2", session_id=app.session_id
    )


@pytest.mark.anyio
async def test_cli_ollama_unavailable_startup_usability(fresh_echo_brain: ECHOBrain) -> None:
    """Verify CLI operates seamlessly when Ollama is offline (DEGRADED state)."""
    console = Console(record=True, width=120)

    degraded_health = SystemHealth(
        overall_status=ComponentStatus.DEGRADED,
        checks=[
            DiagnosticCheck("Python Runtime", ComponentStatus.READY, "3.12 OK", True),
            DiagnosticCheck(
                "Ollama LLM Service", ComponentStatus.DEGRADED, "Ollama offline", False
            ),
        ],
    )

    input_fn = make_scripted_input(["Hello", "/exit"])
    app = CLIApp(
        brain=fresh_echo_brain,
        console=console,
        diagnostics=degraded_health,
        input_fn=input_fn,
    )
    await app.run()

    output = console.export_text()
    assert "DEGRADED" in output
    assert "ECHO" in output
    assert "Exiting ECHO... Goodbye!" in output


@pytest.mark.anyio
async def test_cli_no_secret_leakage(fresh_echo_brain: ECHOBrain) -> None:
    """Verify CLI confirmation card redacts sensitive credentials and does not dump raw secrets."""
    console = Console(record=True, width=120)

    secret_key = "super_secret_api_key_12345"
    pending_action_data = {
        "action_id": "act_secret_test",
        "tool": "api_call",
        "risk_level": "CRITICAL",
        "arguments": {
            "api_key": secret_key,
            "token": "bearer_secret_xyz",
            "safe_param": "regular_value",
        },
    }

    async def fake_secret_process(req: Request) -> str:
        req.context["requires_confirmation"] = True
        req.context["pending_action_id"] = "act_secret_test"
        req.result = MagicMock()
        req.result.requires_confirmation = True
        req.result.pending_action = pending_action_data
        return "Action requires approval."

    fresh_echo_brain.process = fake_secret_process  # type: ignore[assignment]

    input_fn = make_scripted_input(["run api tool", "/cancel", "/exit"])
    app = CLIApp(brain=fresh_echo_brain, console=console, input_fn=input_fn)
    await app.run()

    output = console.export_text()
    # The actual secret values must be redacted by render_confirmation_card
    assert secret_key not in output
    assert "bearer_secret_xyz" not in output
    assert "[REDACTED]" in output


# ---------------------------------------------------------------------------
# main.py Bootstrap and Entrypoint Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_main_version_flag() -> None:
    """Verify main.py --version displays version information and exits with 0."""
    from main import async_main

    exit_code = await async_main(["--version"])
    assert exit_code == 0


@pytest.mark.anyio
async def test_main_status_flag() -> None:
    """Verify main.py --status renders diagnostics and exits with 0."""
    from main import async_main

    exit_code = await async_main(["--status"])
    assert exit_code == 0


@pytest.mark.anyio
async def test_main_blocked_diagnostic_exits_1() -> None:
    """Verify main.py blocks execution with status code 1 when core check fails."""
    from main import async_main

    blocked_health = SystemHealth(
        overall_status=ComponentStatus.BLOCKED,
        checks=[
            DiagnosticCheck("Python Runtime", ComponentStatus.BLOCKED, "Incompatible", True),
        ],
    )

    with patch("main.run_diagnostics", AsyncMock(return_value=blocked_health)):
        exit_code = await async_main([])
        assert exit_code == 1


@pytest.mark.anyio
async def test_main_runs_cli_and_shuts_down() -> None:
    """Verify main.py starts CLI and completes graceful lifecycle shutdown on exit."""
    from main import async_main

    healthy = SystemHealth(
        overall_status=ComponentStatus.READY,
        checks=[
            DiagnosticCheck("Python Runtime", ComponentStatus.READY, "3.12 OK", True),
        ],
    )

    mock_cli_run = AsyncMock()
    with (
        patch("main.run_diagnostics", AsyncMock(return_value=healthy)),
        patch("main.CLIApp.run", mock_cli_run),
        patch("main.lifecycle_manager.shutdown", AsyncMock()) as mock_shutdown,
    ):
        exit_code = await async_main([])
        assert exit_code == 0
        mock_cli_run.assert_awaited_once()
        mock_shutdown.assert_awaited_once()
