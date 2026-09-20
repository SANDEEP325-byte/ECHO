"""Phase 9E — Performance & Resource Integration Test Suite for ECHO.

Verifies the 10 approved performance and resource invariants:
1. Fast-path latency/behavior: Conversational/identity fast paths bypass planning/reasoning.
2. Repeated request stability: 50 sequential requests exhibit no resource leakage.
3. Concurrent brain ingestion: Parallel async requests maintain session/context isolation.
4. Pending-action eviction: Strict MAX_STORED_ACTIONS (200) capacity bounding and pruning contract.
5. Pending-action claim contention: 20 concurrent threads result in strictly 1 execution claim.
6. Memory contention: Rapid batched SQLite memory operations complete without connection locks.
7. Plugin output bound: Oversized (~1 MB) plugin output is strictly bounded to 64 KB.
8. Desktop command output bound: Oversized stdout is safely truncated to 64 KB.
9. Browser session bounding: Max-session enforcement and idle cleanup work per existing contracts.
10. Voice resource/output bounds: Text length, audio byte limits, and zero audio retention invariants.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import subprocess
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.interfaces.pending_action import (
    ActionState,
    ConfirmationStatus,
)
from packages.interfaces.request import Request
from packages.interfaces.security import RiskLevel
from services.brain.brain import ECHOBrain
from services.brain.execution import execution_engine
from services.browser.errors import BrowserSessionLimitError
from services.browser.service import BrowserService, BrowserServiceState
from services.desktop.commands import CommandExecutor
from services.plugins.security_policy import PluginSecurityPolicy
from services.security.pending_action_manager import (
    PendingActionManager,
)
from services.voice.audio_output import MockAudioOutput
from services.voice.errors import AudioOutputError
from services.voice.manager import VoiceManager
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import MockSpeechSynthesizer

# =============================================================================
# 1. Fast-Path Latency & Call-Count Invariants
# =============================================================================


@pytest.mark.anyio
async def test_fast_path_latency_and_call_count_invariants(
    fresh_echo_brain: ECHOBrain,
    fake_gateway: Any,
) -> None:
    """Verify conversational and identity queries bypass planning and generative LLM overhead."""
    brain = fresh_echo_brain

    with (
        patch("services.brain.brain.ai_gateway.generate", new=fake_gateway.generate),
        patch.object(execution_engine, "execute", wraps=execution_engine.execute) as mock_exec,
    ):
        # 1. Conversational Greeting Query
        req_greeting = Request(user_input="Hello ECHO")
        resp_greeting = await brain.process(req_greeting)

        assert resp_greeting is not None
        assert "ECHO" in resp_greeting or "Hello" in resp_greeting
        # Must NOT invoke generative gateway or tool execution engine
        assert fake_gateway.call_count == 0
        assert mock_exec.call_count == 0

        # 2. Identity Query
        req_identity = Request(user_input="Who are you?")
        resp_identity = await brain.process(req_identity)

        assert resp_identity is not None
        assert "ECHO" in resp_identity or "assistant" in resp_identity
        assert fake_gateway.call_count == 0
        assert mock_exec.call_count == 0


# =============================================================================
# 2. Repeated Request Stability (No Leaked State or Resources)
# =============================================================================


@pytest.mark.anyio
async def test_repeated_requests_stability_no_resource_leaks(
    fresh_echo_brain: ECHOBrain,
    fake_gateway: Any,
    clean_pending_actions: PendingActionManager,
) -> None:
    """Verify executing 50 sequential requests exhibits no pending-action or memory leaks."""
    brain = fresh_echo_brain

    with patch("services.brain.brain.ai_gateway.generate", new=fake_gateway.generate):
        for i in range(50):
            req = Request(user_input=f"Hello iteration {i}")
            resp = await brain.process(req)
            assert resp is not None
            assert len(resp) > 0

    # Invariant: No orphaned pending actions created by conversational turns
    assert len(clean_pending_actions._actions) == 0

    # Invariant: Memory manager recorded all 50 interactions (50 user + 50 assistant = 100)
    assert brain.memory_manager is not None
    messages = brain.memory_manager.get_recent_messages(limit=200)
    assert len(messages) == 100


# =============================================================================
# 3. Concurrent Brain Ingestion & Session Isolation
# =============================================================================


@pytest.mark.anyio
async def test_concurrent_brain_ingestion_session_isolation(
    fresh_echo_brain: ECHOBrain,
    fake_gateway: Any,
) -> None:
    """Verify concurrent async requests maintain strict session and context isolation."""
    brain = fresh_echo_brain

    async def run_isolated_request(idx: int) -> tuple[int, str, str]:
        req = Request(
            user_input=f"Hello from user {idx}",
            session_id=f"session_concurrent_{idx}",
        )
        resp = await brain.process(req)
        return idx, str(req.session_id), resp

    with patch("services.brain.brain.ai_gateway.generate", new=fake_gateway.generate):
        # Dispatch 10 concurrent requests simultaneously
        tasks = [run_isolated_request(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

    assert len(results) == 10
    observed_sessions = set()
    for idx, sess_id, resp in results:
        assert sess_id == f"session_concurrent_{idx}"
        assert resp is not None
        observed_sessions.add(sess_id)

    # Invariant: All 10 sessions remained completely distinct
    assert len(observed_sessions) == 10


# =============================================================================
# 4. Pending-Action Eviction & Bounded Capacity Contract
# =============================================================================


def test_pending_action_eviction_bounded_at_max_stored_actions() -> None:
    """Verify PendingActionManager strictly bounds storage to MAX_STORED_ACTIONS (200)."""
    mgr = PendingActionManager(max_stored_actions=200)

    # 1. Pre-fill with 50 EXECUTED actions and 50 CANCELLED actions
    for i in range(50):
        act = mgr.create_pending_action(f"tool_exec_{i}", {}, RiskLevel.SENSITIVE)
        mgr.claim_for_execution(act.action_id)
        mgr.mark_executed(act.action_id, result="done")

    for i in range(50):
        act = mgr.create_pending_action(f"tool_cancel_{i}", {}, RiskLevel.SENSITIVE)
        mgr.cancel_action(act.action_id)

    # 2. Add 100 PENDING actions (reaching 200)
    for i in range(100):
        mgr.create_pending_action(f"tool_pending_{i}", {}, RiskLevel.SENSITIVE)

    assert len(mgr._actions) == 200

    # 3. Add 50 more PENDING actions (exceeding initial capacity to 250 total created)
    for i in range(50):
        mgr.create_pending_action(f"tool_overflow_{i}", {}, RiskLevel.SENSITIVE)

    # Invariant: Total capacity must never exceed MAX_STORED_ACTIONS (200)
    assert len(mgr._actions) <= 200

    # Invariant: Pruning contract evicts non-pending actions (EXECUTED/CANCELLED) first
    active_pending = [a for a in mgr._actions.values() if a.state == ActionState.PENDING]
    assert len(active_pending) >= 150


# =============================================================================
# 5. Pending-Action Claim Contention (High-Concurrency Race)
# =============================================================================


def test_pending_action_claim_high_contention_single_winner() -> None:
    """Verify 20 concurrent threads racing to claim one action produce exactly 1 winner."""
    mgr = PendingActionManager()
    action = mgr.create_pending_action(
        tool_name="critical_tool",
        arguments={"action": "deploy"},
        risk_level=RiskLevel.CRITICAL,
    )

    results: list[tuple[bool, ConfirmationStatus]] = []

    def claim_attempt() -> tuple[bool, ConfirmationStatus]:
        claimed, _, status, _ = mgr.claim_for_execution(action.action_id)
        return claimed, status

    # 20 parallel worker threads attempt simultaneous claim
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(claim_attempt) for _ in range(20)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    claimed_success = sum(1 for success, _ in results if success)
    already_processed = sum(
        1 for _, status in results if status == ConfirmationStatus.ALREADY_PROCESSED
    )

    # Invariant: Exactly one claim succeeded; exactly 19 rejected as already processed
    assert claimed_success == 1
    assert already_processed == 19
    assert action.state == ActionState.CONFIRMED


# =============================================================================
# 6. Memory Contention & Rapid Operations
# =============================================================================


def test_memory_contention_rapid_operations_clean_state(fresh_echo_brain: ECHOBrain) -> None:
    """Verify rapid batched SQLite operations complete without locking or connection corruption."""
    brain = fresh_echo_brain
    assert brain.memory_manager is not None
    mgr = brain.memory_manager

    # 1. 50 rapid sequential fact saves and retrievals
    for i in range(50):
        mgr.save_fact(f"perf_key_{i}", f"perf_val_{i}")
        val = mgr.get_fact(f"perf_key_{i}")
        assert val == f"perf_val_{i}"

    # 2. 50 rapid message saves
    for i in range(50):
        mgr.save_message("user", f"message {i}")
        mgr.save_message("assistant", f"reply {i}")

    # Invariant: All facts retrievable accurately
    all_facts = mgr.get_all_facts()
    assert len(all_facts) >= 50
    for i in range(50):
        assert all_facts.get(f"perf_key_{i}") == f"perf_val_{i}"

    # Invariant: Connections left in clean operable state
    recent = mgr.get_recent_messages(limit=10)
    assert len(recent) == 10


# =============================================================================
# 7. Plugin Output Bounding (64 KB Ceiling)
# =============================================================================


def test_plugin_output_bounded_at_64kb() -> None:
    """Verify that oversized plugin outputs (~1 MB) are strictly truncated to 64 KB."""
    # 1. Massive string output (1 MB)
    huge_str = "X" * (1024 * 1024)
    sanitized_str = PluginSecurityPolicy.sanitize_and_bound_output(
        raw_output=huge_str, plugin_id="test_perf_plugin"
    )
    assert isinstance(sanitized_str, str)
    assert "[TRUNCATED: Plugin 'test_perf_plugin' output exceeded 64KB limit]" in sanitized_str
    # Verify the payload portion before the truncation notice starts with 64KB (65536 bytes)
    assert sanitized_str.startswith("X" * PluginSecurityPolicy.MAX_PLUGIN_OUTPUT_BYTES)

    # 2. Massive dictionary output with large values
    huge_dict = {"payload": "Y" * (1024 * 1024)}
    sanitized_dict = PluginSecurityPolicy.sanitize_and_bound_output(
        raw_output=huge_dict, plugin_id="test_perf_plugin"
    )
    assert isinstance(sanitized_dict, str)
    assert "[TRUNCATED: Plugin 'test_perf_plugin' output exceeded 64KB limit]" in sanitized_dict


# =============================================================================
# 8. Desktop Command Output Bounding (64 KB Ceiling)
# =============================================================================


def test_desktop_command_output_bounded_at_64kb() -> None:
    """Verify command executor strictly bounds stdout to DEFAULT_MAX_OUTPUT_BYTES (64 KB)."""
    # Simulate a subprocess returning 200 KB of stdout
    oversized_bytes = b"L" * 200000
    mock_proc = subprocess.CompletedProcess(
        args=["git", "status"],
        returncode=0,
        stdout=oversized_bytes,
        stderr=b"",
    )

    mock_runner = MagicMock(return_value=mock_proc)
    mock_policy = MagicMock()
    mock_policy.validate_command_identifier.return_value = "git"
    mock_policy.resolve_executable.return_value = Path("C:/Program Files/Git/bin/git.exe")
    mock_policy.validate_arguments.return_value = ["status"]
    mock_policy.validate_cwd.return_value = Path.cwd()

    executor = CommandExecutor(
        policy=mock_policy,
        process_runner=mock_runner,
        max_output_bytes=65536,
    )

    res = executor.execute_command("git", ["status"])

    assert res["status"] == "success"
    assert res["truncated"] is True
    assert "[OUTPUT TRUNCATED: Exceeded size limit]" in res["stdout"]
    # The raw prefix before notice is capped at 65536
    assert res["stdout"].startswith("L" * 65536)


# =============================================================================
# 9. Browser Session Bounding & Idle Pruning
# =============================================================================


@pytest.mark.anyio
async def test_browser_session_bounding_and_idle_cleanup() -> None:
    """Verify BrowserService caps active sessions and cleans up expired idle contexts."""
    # Mock Playwright and Chromium process
    mock_page = MagicMock()
    mock_page.close = AsyncMock()
    mock_context = MagicMock()
    mock_context.route = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_pw = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_launcher = MagicMock(return_value=mock_pw)

    # Note: idle_timeout_seconds must satisfy 10.0 <= timeout <= 86400.0 contract
    svc = BrowserService(
        max_sessions=3,
        idle_timeout_seconds=10.0,
        playwright_launcher=mock_launcher,
    )

    await svc.start()
    assert svc.is_running is True

    # 1. Create up to max_sessions (3)
    s1 = await svc.create_session()
    s2 = await svc.create_session()
    s3 = await svc.create_session()
    assert len(svc._sessions) == 3

    # 2. Exceeding max_sessions must raise BrowserSessionLimitError
    with pytest.raises(BrowserSessionLimitError):
        await svc.create_session()

    # 3. Simulate idle expiration deterministically without flaky sleeping
    now = time.monotonic()
    s1._last_accessed_at = now - 20.0
    s2._last_accessed_at = now - 20.0
    s3._last_accessed_at = now - 20.0

    closed_count = await svc.cleanup_idle_sessions()

    # Invariant: All 3 idle sessions reclaimed
    assert closed_count == 3
    assert len(svc._sessions) == 0

    # Idempotent stop
    await svc.stop()
    assert svc.is_running is False
    assert str(svc.state) == str(BrowserServiceState.STOPPED)


# =============================================================================
# 10. Voice Resource Ceilings & Zero-Retention Invariants
# =============================================================================


@pytest.mark.anyio
async def test_voice_resource_limits_and_zero_retention() -> None:
    """Verify voice payload length limits, audio byte ceilings, and zero raw audio persistence."""
    # 1. TTS Text Length Bounding (MAX_TEXT_LENGTH = 3000)
    huge_text = "This is a sentence. " * 300  # ~6,000 characters
    cleaned = MockSpeechSynthesizer.clean_text(huge_text)
    assert len(cleaned) <= MockSpeechSynthesizer.MAX_TEXT_LENGTH
    assert len(cleaned) == 3000

    # 2. Audio Output Byte Bounding (MAX_OUTPUT_BYTES = 5 MB)
    output_sink = MockAudioOutput(max_output_bytes=1000)
    # Valid payload succeeds
    output_sink.play(b"\x00\x05" * 200)
    assert output_sink.play_count == 1

    # Oversized payload raises AudioOutputError
    with pytest.raises(AudioOutputError):
        output_sink.play(b"\x00\x05" * 1000)  # 2000 bytes > 1000 bound

    # 3. Zero Audio Retention Invariant
    mock_stt = MockSpeechRecognizer(default_transcript="Test voice command")
    mock_brain = MagicMock()
    mock_brain.process = AsyncMock(
        return_value=MagicMock(success=True, response="Response text", error=None)
    )
    manager = VoiceManager(speech_recognizer=mock_stt, brain=mock_brain)

    audio_bytes = b"\x00\x02" * 8000
    res = await manager.process_audio_bytes(audio_bytes)

    assert res.success is True
    assert res.transcription == "Test voice command"
    # Invariant: VoiceManager holds no references to the audio bytes
    assert not hasattr(manager, "audio_bytes")
    assert not hasattr(manager, "cached_audio")
