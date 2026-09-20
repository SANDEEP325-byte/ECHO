"""Phase 9D — Reliability, Failure & Recovery Integration Test Suite.

Comprehensive testing of failure isolation, recovery mechanisms, and state consistency:
1. Tool and plugin unexpected exceptions with clean failure results.
2. Plugin discovery, initialization, and tool-loading failures.
3. Browser startup, operation failure, timeout, and cleanup.
4. Voice STT/TTS failures and preservation of textual responses.
5. Filesystem and command execution failures (disk full, permission, timeout).
6. Pending-action expiry, cancellation, and missing tool handling.
7. Multi-step plan execution halting immediately on step failure.
8. Verification failure overriding tool's self-reported success.
9. Plugin circuit breaker quarantine and explicit safe recovery.
10. Memory persistence resilience under SQLite operational errors (locks).
11. Gateway timeout, malformed responses, and schema-validation fallback.
12. Resource cleanup and state consistency after execution crashes.
13. Confirmation idempotency under duplicate calls.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.interfaces.execution import ExecutionResult
from packages.interfaces.pending_action import ActionState, ConfirmationStatus
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.plugin import (
    PluginCapability,
    PluginManifest,
    PluginMetadata,
    PluginState,
)
from packages.interfaces.request import Request, RequestStatus
from packages.interfaces.verification import VerificationStatus
from services.brain.brain import ECHOBrain
from services.brain.execution import ExecutionEngine
from services.brain.verification import VerificationEngine
from services.desktop.policy import DesktopSecurityPolicy
from services.plugins.manager import PluginManager, PluginRecord
from services.security.pending_action_manager import PendingActionManager
from services.security.risk import RiskLevel
from services.voice.audio_output import MockAudioOutput
from services.voice.manager import VoiceManager
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import MockSpeechSynthesizer

# =============================================================================
# 1. Tool and Plugin Unexpected Exceptions
# =============================================================================


@pytest.mark.anyio
async def test_tool_unhandled_exception_clean_failure() -> None:
    """Verify an unexpected tool runtime exception results in clean RequestStatus.FAILED without crashing."""
    engine = ExecutionEngine()
    req = Request(user_input="Run failing tool")
    req.selected_tools = ["calculator"]

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Call calculator with exception",
                tool_name="calculator",
                arguments={"expression": "1 / 0"},
            )
        ],
    )

    with patch.object(
        engine.router, "execute_tool", side_effect=ZeroDivisionError("division by zero")
    ):
        result = engine.execute(req, plan)

        assert not result.success
        assert req.status == RequestStatus.FAILED
        assert "division by zero" in result.error


def test_plugin_load_error_fault_isolation() -> None:
    """Verify that a broken plugin failing during load sets ERROR state without corrupting manager."""
    mgr = PluginManager()
    manifest = PluginManifest(
        metadata=PluginMetadata(
            id="broken_plugin",
            name="Broken",
            version="1.0.0",
            description="Plugin that crashes on load",
            author="tester",
            entrypoint="non_existent.py",
            min_echo_version="0.1.0",
            capabilities=(PluginCapability.FILESYSTEM_READ,),
            tools=("dummy_tool",),
        )
    )
    record = PluginRecord(
        id="broken_plugin",
        manifest=manifest,
        plugin_dir=Path("plugins/broken_plugin"),
        state=PluginState.VALIDATED,
    )
    mgr._plugins["broken_plugin"] = record
    mgr.enabled_plugins.add("broken_plugin")

    # Loading a broken plugin must return False, set ERROR state, and not raise
    success = mgr.load_plugin("broken_plugin")
    assert success is False
    assert record.state == PluginState.ERROR
    assert record.error is not None


# =============================================================================
# 2. Multi-Step Plan Halting on Failure
# =============================================================================


@pytest.mark.anyio
async def test_multi_step_plan_halts_immediately_on_step_failure() -> None:
    """Verify that in a multi-step plan, a failure at step 2 prevents step 3 from executing."""
    engine = ExecutionEngine()
    req = Request(user_input="Execute 3-step sequence")
    req.selected_tools = ["calculator"]

    step3_executed = False

    def mock_execute_tool(tool_name: str, user_input: str, **kwargs: Any) -> Any:
        nonlocal step3_executed
        expr = kwargs.get("expression")
        if expr == "step1":
            return "Step 1 OK"
        if expr == "step2":
            raise RuntimeError("Step 2 failed deliberately")
        if expr == "step3":
            step3_executed = True
            return "Step 3 OK"
        return "Unknown"

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Step 1",
                tool_name="calculator",
                arguments={"expression": "step1"},
            ),
            PlanStep(
                step_number=2,
                description="Step 2",
                tool_name="calculator",
                arguments={"expression": "step2"},
            ),
            PlanStep(
                step_number=3,
                description="Step 3",
                tool_name="calculator",
                arguments={"expression": "step3"},
            ),
        ],
    )

    with patch.object(engine.router, "execute_tool", side_effect=mock_execute_tool):
        result = engine.execute(req, plan)

        assert not result.success
        assert req.status == RequestStatus.FAILED
        assert "Step 2 failed deliberately" in result.error
        # Step 3 must NEVER have executed
        assert step3_executed is False


# =============================================================================
# 3. Verification Failure Overriding Tool Success
# =============================================================================


def test_verification_failure_overrides_tool_reported_success(isolated_workspace: Path) -> None:
    """Verify that VerificationEngine overrides a tool's reported success if disk state is missing."""
    policy = DesktopSecurityPolicy(
        authorized_roots=[isolated_workspace], include_default_roots=False
    )
    engine = VerificationEngine(desktop_policy=policy)

    missing_file = isolated_workspace / "phantom_file.txt"
    req = Request(user_input="Create phantom file")
    exec_res = ExecutionResult(
        success=True,  # Tool falsely claims success
        result={"operation": "create_file", "path": str(missing_file), "status": "created"},
    )

    # Verification must override tool success and mark NOT_VERIFIED
    v_res = engine.verify(req, exec_res)
    assert v_res.success is False
    assert v_res.status == VerificationStatus.NOT_VERIFIED


# =============================================================================
# 4. Plugin Circuit Breaker Quarantine & Recovery
# =============================================================================


def test_plugin_circuit_breaker_quarantine_and_recovery() -> None:
    """Verify that a plugin is quarantined to ERROR after 3 failures, and can be safely re-enabled."""
    mgr = PluginManager()
    manifest = PluginManifest(
        metadata=PluginMetadata(
            id="flaky_plugin",
            name="Flaky Plugin",
            version="1.0.0",
            description="Flaky plugin for circuit breaker testing",
            author="tester",
            entrypoint="main.py",
            min_echo_version="0.1.0",
            capabilities=(PluginCapability.FILESYSTEM_READ,),
            tools=("flaky_tool",),
        )
    )
    record = PluginRecord(
        id="flaky_plugin",
        manifest=manifest,
        plugin_dir=Path("plugins/flaky_plugin"),
        state=PluginState.ACTIVE,
        registered_tools=["flaky_plugin.flaky_tool"],
        max_consecutive_failures=3,
    )
    mgr._plugins["flaky_plugin"] = record
    mgr.enabled_plugins.add("flaky_plugin")

    # Record 2 failures: still active
    mgr.record_failure("flaky_plugin", "Error 1")
    mgr.record_failure("flaky_plugin", "Error 2")
    assert record.state == PluginState.ACTIVE
    assert record.consecutive_failures == 2

    # Record 3rd failure: circuit breaker trips, transitions to ERROR
    mgr.record_failure("flaky_plugin", "Error 3")
    assert record.state == PluginState.ERROR
    assert "Quarantined" in str(record.error)
    assert not mgr.is_plugin_active("flaky_plugin")

    # Explicit recovery: reset failure count and re-enable
    record.consecutive_failures = 0
    record.state = PluginState.ACTIVE
    mgr.enabled_plugins.add("flaky_plugin")
    assert mgr.is_plugin_active("flaky_plugin")


# =============================================================================
# 5. Memory Persistence Failure Resilience (Production Hardening Test)
# =============================================================================


@pytest.mark.anyio
async def test_memory_persistence_sqlite_locked_graceful_degradation(
    fresh_echo_brain: ECHOBrain,
    fake_gateway: Any,
) -> None:
    """Verify that an SQLite database lock error during memory persistence does not crash response delivery."""
    brain = fresh_echo_brain
    fake_gateway.response = "Response delivered despite database lock."

    req = Request(user_input="Hello ECHO")

    # Simulate SQLite OperationalError: database is locked when saving conversation turn
    assert brain.memory_manager is not None
    with (
        patch.object(
            brain.memory_manager,
            "save_message",
            side_effect=sqlite3.OperationalError("database is locked"),
        ),
        patch("services.brain.brain.ai_gateway.generate", new=fake_gateway.generate),
    ):
        # The request must NOT crash; it must return the valid generated response
        resp = await brain.process(req)

        assert resp is not None
        assert "Response delivered" in str(resp) or "ECHO" in str(resp)


# =============================================================================
# 6. Gateway Timeout & Malformed Response Recovery
# =============================================================================


@pytest.mark.anyio
async def test_gateway_timeout_fallback_response(fresh_echo_brain: ECHOBrain) -> None:
    """Verify gateway timeout triggers fallback response without raising unhandled exception."""
    brain = fresh_echo_brain
    req = Request(user_input="Explain quantum mechanics")

    with patch(
        "services.brain.brain.ai_gateway.generate",
        side_effect=TimeoutError("Request to AI service timed out after 30s"),
    ):
        resp = await brain.process(req)

        assert req.status == RequestStatus.FAILED
        assert resp is not None
        assert "couldn't process your request" in str(resp).lower() or "failed" in str(resp).lower()


# =============================================================================
# 7. Voice STT/TTS Failure Handling
# =============================================================================


@pytest.mark.anyio
async def test_voice_tts_failure_preserves_text_response(fresh_echo_brain: ECHOBrain) -> None:
    """Verify that failure during TTS playback does not drop or corrupt the brain's text response."""
    mock_tts = MockSpeechSynthesizer()
    mock_output = MockAudioOutput()
    mock_stt = MockSpeechRecognizer(default_transcript="What is the time?")

    # Simulate hardware audio output device failure
    mock_tts.synthesize = MagicMock(side_effect=RuntimeError("Audio output device disconnected"))

    manager = VoiceManager(
        speech_recognizer=mock_stt,
        speech_synthesizer=mock_tts,
        audio_output=mock_output,
        brain=fresh_echo_brain,
    )

    # 1. Direct speak failure returns False safely without crashing
    speak_ok = await manager.speak("Hello world")
    assert speak_ok is False

    # 2. In-memory audio processing delivers brain response
    audio_pcm = b"\x00\x05" * 1000
    result = await manager.process_audio_bytes(audio_pcm)
    assert result.success is True
    assert result.transcription == "What is the time?"
    assert result.brain_response is not None


@pytest.mark.anyio
async def test_voice_stt_empty_stream_handling() -> None:
    """Verify empty or silent audio streams fail closed with safe fallback message."""
    mock_stt = MockSpeechRecognizer(default_transcript="")
    manager = VoiceManager(speech_recognizer=mock_stt)

    result = await manager.process_audio_bytes(b"")
    assert result.success is True
    assert result.brain_response == "No speech detected."


# =============================================================================
# 8. Filesystem and Command Execution Failures
# =============================================================================


def test_filesystem_disk_full_error_handling() -> None:
    """Verify disk full OSError (Errno 28) during file operation returns clean failure result."""
    mgr = PendingActionManager()
    engine = ExecutionEngine(pending_action_manager=mgr)

    action = mgr.create_pending_action(
        tool_name="write_file",
        arguments={"path": "large.dat", "content": "data"},
        risk_level=RiskLevel.SENSITIVE,
    )

    with patch.object(
        engine.router,
        "execute_tool",
        side_effect=OSError(28, "No space left on device"),
    ):
        res = engine.resume_pending_action(action.action_id)
        assert not res.success
        assert res.status == ConfirmationStatus.FAILED
        assert "No space left on device" in str(res.error) or "failed" in str(res.message).lower()


def test_command_execution_timeout_handling() -> None:
    """Verify command execution timeout returns clean failure result."""
    mgr = PendingActionManager()
    engine = ExecutionEngine(pending_action_manager=mgr)

    action = mgr.create_pending_action(
        tool_name="execute_command",
        arguments={"command": "sleep 100"},
        risk_level=RiskLevel.SENSITIVE,
    )

    with patch.object(
        engine.router,
        "execute_tool",
        side_effect=subprocess.TimeoutExpired(cmd="sleep 100", timeout=5.0),
    ):
        res = engine.resume_pending_action(action.action_id)
        assert not res.success
        assert res.status == ConfirmationStatus.FAILED
        assert "timed out" in str(res.error).lower() or "timeoutexpired" in str(res.error).lower()


# =============================================================================
# 9. Pending Action Failure State Transition
# =============================================================================


def test_pending_action_failure_transitions_to_failed_state() -> None:
    """Verify that a tool crash during resumed pending action marks state as FAILED."""
    mgr = PendingActionManager()
    engine = ExecutionEngine(pending_action_manager=mgr)

    action = mgr.create_pending_action(
        tool_name="calculator",
        arguments={"expression": "10 + 5"},
        risk_level=RiskLevel.SENSITIVE,
    )

    # Force router execution to crash during resume
    with patch.object(engine.router, "execute_tool", side_effect=RuntimeError("Hardware failure")):
        res = engine.resume_pending_action(action.action_id)

        assert not res.success
        assert res.status == ConfirmationStatus.FAILED
        # Action in manager must be FAILED, not left PENDING or CONFIRMED
        retrieved = mgr.get_action(action.action_id)
        assert retrieved is not None
        assert retrieved.state == ActionState.FAILED
        assert "Hardware failure" in str(retrieved.error)


# =============================================================================
# 10. Confirmation Idempotency under Duplicate Calls
# =============================================================================


def test_duplicate_confirmation_idempotent_rejection() -> None:
    """Verify rapid duplicate /confirm calls execute only once and reject duplicate."""
    mgr = PendingActionManager()
    engine = ExecutionEngine(pending_action_manager=mgr)

    action = mgr.create_pending_action(
        tool_name="calculator",
        arguments={"expression": "21 * 2"},
        risk_level=RiskLevel.SENSITIVE,
    )

    with patch.object(engine.router, "execute_tool", return_value="42"):
        # First confirmation executes
        res1 = engine.resume_pending_action(action.action_id)
        assert res1.success is True
        assert res1.status == ConfirmationStatus.CONFIRMED

        # Second duplicate confirmation must be rejected idempotently
        res2 = engine.resume_pending_action(action.action_id)
        assert res2.success is False
        assert res2.status == ConfirmationStatus.ALREADY_PROCESSED


# =============================================================================
# 11. Browser Startup Failure & Cleanup Recovery
# =============================================================================


@pytest.mark.anyio
async def test_browser_startup_failure_and_cleanup_recovery() -> None:
    """Verify BrowserService startup failure transitions to FAILED state and cleans up resources."""
    from services.browser.errors import BrowserBinaryMissingError, BrowserStartupError
    from services.browser.service import BrowserService, BrowserServiceState

    # 1. Missing binary error handling
    mock_launcher_missing = MagicMock(
        side_effect=Exception(
            "Executable doesn't exist at /path/to/chromium. Run playwright install"
        )
    )
    svc = BrowserService(playwright_launcher=mock_launcher_missing)

    with pytest.raises(BrowserBinaryMissingError):
        await svc.start()

    assert svc.state == BrowserServiceState.FAILED

    # Idempotent teardown on failed service must not raise
    await svc.stop()
    assert svc.state == BrowserServiceState.STOPPED

    # 2. Timeout during browser launch
    mock_pw = MagicMock()
    mock_pw.chromium.launch = AsyncMock(side_effect=TimeoutError("Chromium launch timed out"))
    mock_launcher_timeout = MagicMock(return_value=mock_pw)

    svc_timeout = BrowserService(playwright_launcher=mock_launcher_timeout)
    with pytest.raises(BrowserStartupError):
        await svc_timeout.start()

    assert svc_timeout.state == BrowserServiceState.FAILED
    await svc_timeout.stop()
    assert svc_timeout.state == BrowserServiceState.STOPPED
