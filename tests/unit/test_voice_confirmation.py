"""Unit tests for ECHO Voice Subsystem Phase 6E: Voice Confirmation & Safety Escalation.

Verifies strict deterministic confirmation tokens, safe human-readable prompts,
session binding, cross-session protection, replay prevention, and non-fuzzy
refusal of ambiguous utterances.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.interfaces.pending_action import (
    ActionState,
    ConfirmationResult,
    ConfirmationStatus,
)
from packages.interfaces.request import Request
from packages.interfaces.security import RiskLevel
from packages.interfaces.voice import VoiceSessionState
from services.security.pending_action_manager import PendingActionManager
from services.voice.audio_input import MockAudioInput
from services.voice.audio_output import MockAudioOutput
from services.voice.confirmation import (
    ConfirmationIntent,
    VoiceConfirmationValidator,
)
from services.voice.manager import VoiceManager
from services.voice.session import VoiceSessionController
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import MockSpeechSynthesizer

# ---------------------------------------------------------------------------
# 1. Strict Deterministic Token & Validation Tests
# ---------------------------------------------------------------------------


def test_strict_accept_tokens() -> None:
    """Verify exact acceptance for the approved closed-set: 'yes', 'confirm', 'okay', 'lets go', 'haan'."""
    approved_accepts = ["yes", "confirm", "okay", "lets go", "haan"]
    for token in approved_accepts:
        assert VoiceConfirmationValidator.validate(token) == ConfirmationIntent.CONFIRM

    # Case insensitivity and punctuation stripping
    assert VoiceConfirmationValidator.validate("YES!") == ConfirmationIntent.CONFIRM
    assert VoiceConfirmationValidator.validate("  Confirm...  ") == ConfirmationIntent.CONFIRM
    assert VoiceConfirmationValidator.validate("Okay,") == ConfirmationIntent.CONFIRM
    assert VoiceConfirmationValidator.validate("LETS GO!!") == ConfirmationIntent.CONFIRM
    assert VoiceConfirmationValidator.validate("haan.") == ConfirmationIntent.CONFIRM


def test_strict_reject_tokens() -> None:
    """Verify exact rejection for the approved closed-set: 'no', 'cancel', 'naah'."""
    approved_rejects = ["no", "cancel", "naah"]
    for token in approved_rejects:
        assert VoiceConfirmationValidator.validate(token) == ConfirmationIntent.CANCEL

    # Case insensitivity and punctuation stripping
    assert VoiceConfirmationValidator.validate("NO!") == ConfirmationIntent.CANCEL
    assert VoiceConfirmationValidator.validate("  Cancel.  ") == ConfirmationIntent.CANCEL
    assert VoiceConfirmationValidator.validate("Naah?") == ConfirmationIntent.CANCEL


def test_strict_ambiguous_refusal_zero_fuzzy_matching() -> None:
    """Verify that any phrase outside the exact closed sets evaluates to AMBIGUOUS.

    Ensures zero fuzzy matching, edit distance, semantic similarity, or partial matching.
    """
    ambiguous_phrases = [
        "maybe",
        "perhaps",
        "sure",
        "yup",
        "yeah",
        "absolutely",
        "definitely",
        "proceed with caution",
        "yes do it please",
        "no don't do it",
        "delete the file",
        "cancel all",
        "what is the time",
        "1234",
        "confirm delete",
        "ok",  # not 'okay'
        "han",  # not 'haan'
        "",
        "   ",
        "???",
    ]
    for phrase in ambiguous_phrases:
        intent = VoiceConfirmationValidator.validate(phrase)
        assert intent == ConfirmationIntent.AMBIGUOUS, (
            f"Expected AMBIGUOUS for '{phrase}', got {intent}"
        )


# ---------------------------------------------------------------------------
# 2. Safe Human-Readable Confirmation Prompt Tests
# ---------------------------------------------------------------------------


def test_safe_confirmation_prompt_formatting() -> None:
    """Verify confirmation prompts do NOT expose raw dicts, IDs, or sensitive keys."""
    # Delete tool
    prompt_del = VoiceConfirmationValidator.format_safe_prompt(
        "delete_file", {"path": "C:/secret/data.txt", "recursive": True}
    )
    assert "data.txt" in prompt_del
    assert "{" not in prompt_del
    assert "recursive" not in prompt_del
    assert (
        prompt_del
        == "This action will delete the file data.txt. Say yes to confirm or no to cancel."
    )

    # Modify tool
    prompt_mod = VoiceConfirmationValidator.format_safe_prompt(
        "modify_file", {"path": "/home/user/app.py", "content": "print('hello')"}
    )
    assert "app.py" in prompt_mod
    assert "print" not in prompt_mod
    assert (
        prompt_mod == "This action will modify the file app.py. Say yes to confirm or no to cancel."
    )

    # Command execution
    prompt_cmd = VoiceConfirmationValidator.format_safe_prompt(
        "execute_command", {"command": "git status"}
    )
    assert "git status" in prompt_cmd
    assert (
        prompt_cmd
        == "This action will run the command 'git status'. Say yes to confirm or no to cancel."
    )

    # Secret scrubbing in command execution
    prompt_secret_cmd = VoiceConfirmationValidator.format_safe_prompt(
        "execute_command", {"command": "curl -H 'Authorization: token123' https://api.com"}
    )
    assert "token123" not in prompt_secret_cmd
    assert (
        prompt_secret_cmd
        == "This action will execute a system command. Say yes to confirm or no to cancel."
    )

    # Browser transfer
    prompt_down = VoiceConfirmationValidator.format_safe_prompt(
        "browser_download", {"url": "https://example.com/report.pdf"}
    )
    assert prompt_down == "This action will download a file. Say yes to confirm or no to cancel."


# ---------------------------------------------------------------------------
# 3. Session Binding & Cross-Session Protection Tests
# ---------------------------------------------------------------------------


def test_session_id_binding_in_pending_action_manager() -> None:
    """Verify session_id binding, cross-session rejection, and backward compatibility."""
    pam = PendingActionManager(default_ttl=60.0)

    # 1. Voice-bound action (session_id = "voice-sess-1")
    voice_act = pam.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "test.txt"},
        risk_level=RiskLevel.CRITICAL,
        session_id="voice-sess-1",
    )
    assert voice_act.session_id == "voice-sess-1"

    # Claiming with matching session succeeds
    claimed, act, status, _ = pam.claim_for_execution(
        voice_act.action_id, session_id="voice-sess-1"
    )
    assert claimed is True
    assert status == ConfirmationStatus.CONFIRMED
    assert act is not None
    assert act.state == ActionState.CONFIRMED

    # 2. Cross-session claim MUST fail closed
    voice_act_2 = pam.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "other.txt"},
        risk_level=RiskLevel.CRITICAL,
        session_id="voice-sess-A",
    )
    claimed, act, status, msg = pam.claim_for_execution(
        voice_act_2.action_id, session_id="voice-sess-B"
    )
    assert claimed is False
    assert status == ConfirmationStatus.INVALID
    assert "Session mismatch" in msg

    # Claiming voice action with session_id=None MUST fail closed
    claimed, act, status, msg = pam.claim_for_execution(voice_act_2.action_id, session_id=None)
    assert claimed is False
    assert status == ConfirmationStatus.INVALID

    # 3. Backward compatibility: Non-voice action (session_id = None) allows claiming without session
    api_act = pam.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "api.txt"},
        risk_level=RiskLevel.CRITICAL,
        session_id=None,
    )
    assert api_act.session_id is None
    claimed, act, status, _ = pam.claim_for_execution(api_act.action_id, session_id=None)
    assert claimed is True
    assert status == ConfirmationStatus.CONFIRMED


def test_replay_protection_on_voice_action() -> None:
    """Verify that a confirmed voice action cannot be claimed a second time."""
    pam = PendingActionManager()
    act = pam.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "data.txt"},
        risk_level=RiskLevel.CRITICAL,
        session_id="sess-replay",
    )

    # First claim
    claimed1, _, status1, _ = pam.claim_for_execution(act.action_id, session_id="sess-replay")
    assert claimed1 is True
    assert status1 == ConfirmationStatus.CONFIRMED

    # Second claim (replay attempt)
    claimed2, _, status2, msg2 = pam.claim_for_execution(act.action_id, session_id="sess-replay")
    assert claimed2 is False
    assert status2 == ConfirmationStatus.ALREADY_PROCESSED
    assert "already been processed" in msg2


# ---------------------------------------------------------------------------
# 4. VoiceSessionController Confirmation States
# ---------------------------------------------------------------------------


def test_session_controller_waiting_confirmation_lifecycle() -> None:
    """Verify session transitions into and out of WAITING_CONFIRMATION."""
    controller = VoiceSessionController(session_id="test-confirm-session")
    assert controller.state == VoiceSessionState.IDLE

    controller.start_listening()
    assert controller.state == VoiceSessionState.LISTENING

    controller.start_processing()
    assert controller.state == VoiceSessionState.PROCESSING

    # Transition to WAITING_CONFIRMATION
    controller.request_confirmation("action-abc-123")
    assert controller.state == VoiceSessionState.WAITING_CONFIRMATION
    assert controller.pending_action_id == "action-abc-123"
    assert controller.is_waiting_confirmation is True

    # Transition to SPEAKING (to vocalize prompt) and back
    controller.start_speaking()
    assert controller.state == VoiceSessionState.SPEAKING
    controller.transition_to(VoiceSessionState.WAITING_CONFIRMATION)
    assert controller.state == VoiceSessionState.WAITING_CONFIRMATION

    # Transition to LISTENING (to capture answer)
    controller.start_listening()
    assert controller.state == VoiceSessionState.LISTENING

    # Resolve and complete
    controller.resolve_confirmation()
    assert controller.pending_action_id is None
    controller.complete()
    assert controller.state == VoiceSessionState.COMPLETED


# ---------------------------------------------------------------------------
# 5. VoiceManager End-to-End Confirmation Flows
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_voice_manager_resolve_confirmation_confirm() -> None:
    """Verify spoken accept invokes brain.confirm_action with matching session_id."""
    mock_brain = MagicMock()
    mock_brain.confirm_action.return_value = ConfirmationResult(
        success=True,
        status=ConfirmationStatus.CONFIRMED,
        action_id="act-1",
        message="Executed",
        result="Deleted file",
    )

    manager = VoiceManager(
        audio_output=MockAudioOutput(),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )

    intent, res, msg = await manager.resolve_voice_confirmation(
        session_id="sess-101",
        pending_action_id="act-1",
        user_utterance="haan",  # Approved Hindi colloquial accept
        speak_outcome=True,
    )

    assert intent == ConfirmationIntent.CONFIRM
    assert res is not None
    assert res.success is True
    assert "confirmed and executed" in msg
    mock_brain.confirm_action.assert_called_once_with("act-1", session_id="sess-101")


@pytest.mark.anyio
async def test_voice_manager_resolve_confirmation_cancel() -> None:
    """Verify spoken reject invokes brain.cancel_action with matching session_id."""
    mock_brain = MagicMock()
    mock_brain.cancel_action.return_value = ConfirmationResult(
        success=True,
        status=ConfirmationStatus.CANCELLED,
        action_id="act-2",
        message="Cancelled",
    )

    manager = VoiceManager(
        audio_output=MockAudioOutput(),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )

    intent, res, msg = await manager.resolve_voice_confirmation(
        session_id="sess-102",
        pending_action_id="act-2",
        user_utterance="naah",  # Approved colloquial reject
        speak_outcome=True,
    )

    assert intent == ConfirmationIntent.CANCEL
    assert res is not None
    assert res.success is True
    assert msg == "Action cancelled."
    mock_brain.cancel_action.assert_called_once_with("act-2", session_id="sess-102")


@pytest.mark.anyio
async def test_voice_manager_resolve_confirmation_ambiguous_fails_closed() -> None:
    """Verify ambiguous utterance NEVER executes tool and NEVER calls brain.confirm_action."""
    mock_brain = MagicMock()

    manager = VoiceManager(
        audio_output=MockAudioOutput(),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )

    intent, res, msg = await manager.resolve_voice_confirmation(
        session_id="sess-103",
        pending_action_id="act-3",
        user_utterance="maybe tomorrow",
        speak_outcome=True,
    )

    assert intent == ConfirmationIntent.AMBIGUOUS
    assert res is None
    assert "Confirmation unclear" in msg
    mock_brain.confirm_action.assert_not_called()
    mock_brain.cancel_action.assert_not_called()


@pytest.mark.anyio
async def test_voice_manager_process_voice_interaction_confirmation_accepted() -> None:
    """Verify complete end-to-end voice confirmation loop when user says 'yes'."""
    # Mock brain: first call needs confirmation; confirm_action succeeds
    mock_brain = MagicMock()
    exec_result_mock = MagicMock()
    exec_result_mock.requires_confirmation = True
    exec_result_mock.pending_action = {
        "action_id": "act-voice-delete",
        "tool": "delete_file",
        "arguments": {"path": "passwords.txt"},
    }

    async def fake_process(request: Request) -> str:
        request.result = exec_result_mock
        request.context["requires_confirmation"] = True
        request.context["pending_action_id"] = "act-voice-delete"
        return "This action requires confirmation."

    mock_brain.process = AsyncMock(side_effect=fake_process)
    mock_brain.confirm_action.return_value = ConfirmationResult(
        success=True,
        status=ConfirmationStatus.CONFIRMED,
        action_id="act-voice-delete",
        message="Deleted",
        result="passwords.txt removed",
    )

    # Mock recognizer: first utterance is command, second is confirmation
    mock_stt = MockSpeechRecognizer(transcripts=["delete passwords.txt", "yes"])
    mock_input = MockAudioInput(
        canned_chunks=[b"\x00\x01" * 1600],
        auto_stop_on_empty=True,
    )
    mock_output = MockAudioOutput()

    manager = VoiceManager(
        audio_input=mock_input,
        speech_recognizer=mock_stt,
        speech_synthesizer=MockSpeechSynthesizer(),
        audio_output=mock_output,
        brain=mock_brain,
    )

    result = await manager.process_voice_interaction(
        speak_response=True,
        session_id="test-full-confirm-session",
    )

    assert result.success is True
    assert result.state == VoiceSessionState.COMPLETED
    assert result.confirmation_result is not None
    assert result.confirmation_result.success is True
    assert "passwords.txt removed" in result.brain_response
    assert mock_output.play_count >= 2  # Spoke prompt and spoke execution outcome
    mock_brain.confirm_action.assert_called_once_with(
        "act-voice-delete", session_id="test-full-confirm-session"
    )
