"""Unit tests for ECHO Phase 7E: Voice & Coding Safety Integration.

Verifies:
- Safe confirmation prompts for modify_code, apply_patch, run_tests.
- Safe vocal outcome formatting (no diffs, code content, stack traces, or secrets spoken).
- Safe failure vocalizations.
- Rejection of raw dictionaries and sensitive keys in vocal output.
- Spoken affirmative ('yes'), rejection ('cancel'), and ambiguous confirmation flows.
- Cross-session claim rejection.
- Natural spoken request "explain this code" classification.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.interfaces.pending_action import (
    ConfirmationResult,
    ConfirmationStatus,
)
from packages.interfaces.security import RiskLevel
from services.coding.cognition import CodingCognition, CodingSubIntent
from services.security.pending_action_manager import PendingActionManager
from services.voice.audio_input import MockAudioInput
from services.voice.audio_output import MockAudioOutput
from services.voice.confirmation import (
    ConfirmationIntent,
    VoiceConfirmationValidator,
)
from services.voice.manager import VoiceManager
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import MockSpeechSynthesizer

# ---------------------------------------------------------------------------
# 1. Safe Confirmation Prompts for Coding Tools
# ---------------------------------------------------------------------------


def test_safe_prompt_modify_code() -> None:
    """Verify modify_code prompt includes target filename and no secrets or diffs."""
    prompt = VoiceConfirmationValidator.format_safe_prompt(
        "modify_code",
        {
            "file_path": "services/auth.py",
            "target_block": "def secret_key(): return '12345'",
            "replacement_block": "def secret_key(): return 'ABCDE'",
        },
    )
    assert "auth.py" in prompt
    assert "12345" not in prompt
    assert "ABCDE" not in prompt
    assert "{" not in prompt
    assert prompt == "This action will modify the file auth.py. Say yes to confirm or no to cancel."


def test_safe_prompt_apply_patch() -> None:
    """Verify apply_patch prompt includes target filename and no patch contents."""
    prompt = VoiceConfirmationValidator.format_safe_prompt(
        "apply_patch",
        {
            "file_path": "packages/config.py",
            "patch": "--- a/packages/config.py\n+++ b/packages/config.py\n@@ -1,3 +1,3 @@\n-old\n+new",
        },
    )
    assert "config.py" in prompt
    assert "--- a/" not in prompt
    assert "old" not in prompt
    assert (
        prompt
        == "This action will apply a patch to the file config.py. Say yes to confirm or no to cancel."
    )


def test_safe_prompt_run_tests_with_target() -> None:
    """Verify run_tests prompt includes target test file when provided."""
    prompt = VoiceConfirmationValidator.format_safe_prompt(
        "run_tests",
        {
            "framework": "pytest",
            "targets": ["tests/unit/test_auth.py"],
        },
    )
    assert "test_auth.py" in prompt
    assert (
        prompt == "This action will run tests on test_auth.py. Say yes to confirm or no to cancel."
    )


def test_safe_prompt_run_tests_workspace_scope() -> None:
    """Verify run_tests prompt falls back cleanly to workspace scope when no targets given."""
    prompt = VoiceConfirmationValidator.format_safe_prompt(
        "run_tests",
        {"framework": "pytest"},
    )
    assert (
        prompt == "This action will run tests in the workspace. Say yes to confirm or no to cancel."
    )


# ---------------------------------------------------------------------------
# 2. Safe Vocal Result Formatting (No Raw Dictionaries or Diffs)
# ---------------------------------------------------------------------------


def test_safe_vocal_result_modify_code_success() -> None:
    """Verify modify_code vocal summary mentions filename and NEVER speaks raw diff."""
    raw_diff = "--- a/auth.py\n+++ b/auth.py\n@@ -1,2 +1,2 @@\n-token = 'secret'\n+token = 'safe'\n"
    vocal = VoiceConfirmationValidator.format_safe_vocal_result(
        tool_name="modify_code",
        result={
            "operation": "modify_code",
            "success": True,
            "file_path": "auth.py",
            "target_path": "auth.py",
            "diff": raw_diff,
            "syntax_status": "valid",
        },
        success=True,
    )
    assert vocal == "Action confirmed. Modified auth.py successfully."
    assert "token" not in vocal
    assert "diff" not in vocal
    assert "secret" not in vocal
    assert "---" not in vocal
    assert "{" not in vocal


def test_safe_vocal_result_apply_patch_success() -> None:
    """Verify apply_patch vocal summary mentions target and omits diff."""
    vocal = VoiceConfirmationValidator.format_safe_vocal_result(
        tool_name="apply_patch",
        result={
            "operation": "apply_patch",
            "success": True,
            "file_path": "utils.py",
            "target_path": "utils.py",
            "diff": "@@ -10 +10 @@",
        },
        success=True,
    )
    assert vocal == "Action confirmed. Patch applied successfully to utils.py."
    assert "@@" not in vocal
    assert "{" not in vocal


def test_safe_vocal_result_run_tests_passed() -> None:
    """Verify run_tests vocal summary reports counts and omits stdout/tracebacks."""
    stdout_with_traceback = (
        "Traceback (most recent call last):\n  File 'app.py', line 10\n    assert False"
    )
    vocal = VoiceConfirmationValidator.format_safe_vocal_result(
        tool_name="run_tests",
        result={
            "operation": "run_tests",
            "success": True,
            "summary": {"passed": 4, "failed": 0, "skipped": 1},
            "stdout": stdout_with_traceback,
            "stderr": "DEBUG: API_KEY=xyz",
        },
        success=True,
    )
    assert vocal == "Tests passed: 4 passed, 0 failed."
    assert "Traceback" not in vocal
    assert "API_KEY" not in vocal
    assert "stdout" not in vocal


def test_safe_vocal_result_run_tests_failed() -> None:
    """Verify failed run_tests vocal summary reports counts safely without tracebacks."""
    vocal = VoiceConfirmationValidator.format_safe_vocal_result(
        tool_name="run_tests",
        result={
            "operation": "run_tests",
            "success": False,
            "summary": {"passed": 2, "failed": 1},
            "stdout": "FAIL: test_broken",
        },
        success=False,
    )
    assert vocal == "Tests did not pass: 2 passed, 1 failed."
    assert "FAIL" not in vocal


def test_safe_vocal_result_failed_action_generic() -> None:
    """Verify failed mutations return safe generic messages without internal exceptions."""
    vocal = VoiceConfirmationValidator.format_safe_vocal_result(
        tool_name="modify_code",
        result={"error": "SyntaxError: invalid syntax at line 42 with token 'XYZ'"},
        success=False,
        error_message="Low-level internal engine error: memory dump at 0xdeadbeef",
    )
    assert vocal == "The action could not be completed."
    assert "0xdeadbeef" not in vocal
    assert "SyntaxError" not in vocal


def test_safe_vocal_result_unknown_structure_fails_closed() -> None:
    """Verify unexpected/arbitrary structures fail closed to safe message."""
    vocal = VoiceConfirmationValidator.format_safe_vocal_result(
        tool_name="unknown_tool",
        result={"deep": {"nested": "payload", "key": "secret"}},
        success=True,
    )
    assert vocal == "Action confirmed and executed successfully."
    assert "secret" not in vocal
    assert "{" not in vocal


# ---------------------------------------------------------------------------
# 3. Voice Confirmation Execution Flow & Session Binding
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_resolve_voice_confirmation_affirmative_flow() -> None:
    """Verify user saying 'yes' executes confirmed action through Brain with safe vocal message."""
    mock_brain = MagicMock()
    mock_brain.get_pending_action.return_value = MagicMock(tool_name="modify_code")
    mock_brain.confirm_action.return_value = ConfirmationResult(
        success=True,
        status=ConfirmationStatus.CONFIRMED,
        action_id="act-123",
        message="Action confirmed and executed successfully.",
        result={"operation": "modify_code", "file_path": "auth.py", "diff": "--- diff ---"},
    )

    vm = VoiceManager(
        audio_input=MockAudioInput(),
        audio_output=MockAudioOutput(),
        speech_recognizer=MockSpeechRecognizer("yes"),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )
    speak_mock = AsyncMock()
    setattr(vm, "speak", speak_mock)

    intent, confirm_res, msg = await vm.resolve_voice_confirmation(
        session_id="sess-001",
        pending_action_id="act-123",
        user_utterance="yes",
        speak_outcome=True,
    )

    assert intent == ConfirmationIntent.CONFIRM
    assert confirm_res is not None
    assert confirm_res.success is True
    assert msg == "Action confirmed. Modified auth.py successfully."
    # TTS must be called with safe message, not raw dict
    speak_mock.assert_called_once_with(msg, session_id="sess-001")


@pytest.mark.anyio
async def test_resolve_voice_confirmation_cancel_flow() -> None:
    """Verify user saying 'cancel' cancels pending action without executing tools."""
    mock_brain = MagicMock()
    mock_brain.cancel_action.return_value = ConfirmationResult(
        success=True,
        status=ConfirmationStatus.CANCELLED,
        action_id="act-123",
        message="Action cancelled.",
    )

    vm = VoiceManager(
        audio_input=MockAudioInput(),
        audio_output=MockAudioOutput(),
        speech_recognizer=MockSpeechRecognizer("cancel"),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )
    speak_mock = AsyncMock()
    setattr(vm, "speak", speak_mock)

    intent, cancel_res, msg = await vm.resolve_voice_confirmation(
        session_id="sess-001",
        pending_action_id="act-123",
        user_utterance="cancel",
        speak_outcome=True,
    )

    assert intent == ConfirmationIntent.CANCEL
    assert cancel_res is not None
    assert msg == "Action cancelled."
    mock_brain.confirm_action.assert_not_called()
    speak_mock.assert_called_once_with("Action cancelled.", session_id="sess-001")


@pytest.mark.anyio
async def test_resolve_voice_confirmation_ambiguous_flow() -> None:
    """Verify ambiguous utterance never executes tools or confirms actions."""
    mock_brain = MagicMock()

    vm = VoiceManager(
        audio_input=MockAudioInput(),
        audio_output=MockAudioOutput(),
        speech_recognizer=MockSpeechRecognizer("maybe later"),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )
    speak_mock = AsyncMock()
    setattr(vm, "speak", speak_mock)

    intent, res, msg = await vm.resolve_voice_confirmation(
        session_id="sess-001",
        pending_action_id="act-123",
        user_utterance="maybe later",
        speak_outcome=True,
    )

    assert intent == ConfirmationIntent.AMBIGUOUS
    assert res is None
    assert "Confirmation unclear" in msg
    mock_brain.confirm_action.assert_not_called()
    mock_brain.cancel_action.assert_not_called()


def test_cross_session_claim_rejection() -> None:
    """Verify pending action bound to voice session cannot be claimed across sessions."""
    pam = PendingActionManager(default_ttl=60.0)
    action = pam.create_pending_action(
        tool_name="modify_code",
        arguments={"file_path": "auth.py"},
        risk_level=RiskLevel.SENSITIVE,
        session_id="session-alice",
    )

    # Cross-session claim from session-bob fails closed
    claimed, _, status, message = pam.claim_for_execution(
        action.action_id, session_id="session-bob"
    )
    assert not claimed
    assert status == ConfirmationStatus.INVALID
    assert "Session mismatch" in message

    # Same session claim succeeds
    claimed_ok, _, status_ok, _ = pam.claim_for_execution(
        action.action_id, session_id="session-alice"
    )
    assert claimed_ok
    assert status_ok == ConfirmationStatus.CONFIRMED


# ---------------------------------------------------------------------------
# 4. Spoken Request "explain this code" Intent Classification
# ---------------------------------------------------------------------------


def test_classify_explain_this_code() -> None:
    """Verify natural spoken 'explain this code' classifies as CodingSubIntent.EXPLAIN."""
    cognition = CodingCognition()
    is_coding, sub_intent, confidence = cognition.classify_coding_intent("explain this code")
    assert is_coding is True
    assert sub_intent == CodingSubIntent.EXPLAIN
    assert confidence >= 0.9


def test_general_voice_request_not_classified_as_coding() -> None:
    """Verify general conversational voice requests are not falsely treated as coding."""
    cognition = CodingCognition()
    is_coding, sub_intent, _ = cognition.classify_coding_intent("What is the weather like today?")
    assert is_coding is False
    assert sub_intent is None
