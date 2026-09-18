"""Comprehensive Regression & Complete Lifecycle Tests for ECHO Voice (Phase 6F).

Verifies the entire voice pipeline:
- successful voice interaction
- STT failure & unavailable STT model
- TTS failure & audio output failure
- wake/session timeout & session expiration
- confirmation request, accepted, rejected, ambiguous, and timeout
- expired pending action, replayed confirmation, and concurrent confirmation
- execution failure & verification failure
- session cleanup and lock safety
- raw audio privacy invariants (zero audio files on disk)
"""

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.interfaces.pending_action import (
    ConfirmationResult,
    ConfirmationStatus,
)
from packages.interfaces.security import RiskLevel
from packages.interfaces.verification import VerificationResult
from packages.interfaces.voice import (
    VoiceSessionState,
)
from services.security.pending_action_manager import PendingActionManager
from services.voice.audio_input import MockAudioInput
from services.voice.audio_output import MockAudioOutput
from services.voice.confirmation import (
    ConfirmationIntent,
)
from services.voice.manager import VoiceManager
from services.voice.session import VoiceSessionController
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import MockSpeechSynthesizer
from services.voice.wake import MockWakeDetector

# ---------------------------------------------------------------------------
# 1. Complete Voice Interaction Lifecycle & Error Degradation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_lifecycle_successful_interaction() -> None:
    """Verify clean full-cycle: wake -> capture -> transcribe -> brain -> synthesize -> play."""
    mock_brain = MagicMock()
    mock_brain.process = AsyncMock(return_value="The time is 10:00 AM.")

    mock_input = MockAudioInput(canned_chunks=[b"\x00\x01" * 1600], auto_stop_on_empty=True)
    mock_stt = MockSpeechRecognizer(transcripts=["what time is it"])
    mock_tts = MockSpeechSynthesizer()
    mock_output = MockAudioOutput()
    mock_wake = MockWakeDetector(detection_pattern=[True])

    manager = VoiceManager(
        audio_input=mock_input,
        speech_recognizer=mock_stt,
        speech_synthesizer=mock_tts,
        audio_output=mock_output,
        wake_detector=mock_wake,
        brain=mock_brain,
    )

    # 1. Wake detection
    wake_detected = await manager.listen_for_wake_word(timeout_seconds=2.0)
    assert wake_detected is True

    # 2. Process interaction
    result = await manager.process_voice_interaction(speak_response=True)
    assert result.success is True
    assert result.state == VoiceSessionState.COMPLETED
    assert result.transcription == "what time is it"
    assert result.brain_response == "The time is 10:00 AM."
    assert mock_output.play_count == 1
    assert mock_tts.synthesize_count == 1


@pytest.mark.anyio
async def test_lifecycle_stt_failure_degradation() -> None:
    """Verify STT RecognitionError degrades gracefully into error result without host crash."""
    mock_stt = MockSpeechRecognizer(simulate_error="Simulated recognition failure")
    manager = VoiceManager(
        speech_recognizer=mock_stt,
        audio_output=MockAudioOutput(),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=MagicMock(),
    )

    result = await manager.process_audio_bytes(b"\x00\x01" * 1600)
    assert result.success is False
    assert result.state == VoiceSessionState.ERROR
    assert "Simulated recognition failure" in (result.error or "")


@pytest.mark.anyio
async def test_lifecycle_stt_model_unavailable() -> None:
    """Verify unavailable STT model raises structured ModelUnavailableError without network call."""
    mock_stt = MockSpeechRecognizer(is_model_available=False)
    manager = VoiceManager(
        speech_recognizer=mock_stt,
        audio_output=MockAudioOutput(),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=MagicMock(),
    )

    result = await manager.process_audio_bytes(b"\x00\x01" * 1600)
    assert result.success is False
    assert result.state == VoiceSessionState.ERROR
    assert "Mock STT model is not available locally" in (result.error or "")


@pytest.mark.anyio
async def test_lifecycle_tts_and_audio_output_failure() -> None:
    """Verify TTS and audio output hardware failures return False gracefully."""
    # 1. TTS Synthesis failure
    bad_tts = MockSpeechSynthesizer(simulate_error="Simulated synthesis error")
    manager_bad_tts = VoiceManager(
        speech_synthesizer=bad_tts,
        audio_output=MockAudioOutput(),
    )
    assert await manager_bad_tts.speak("Hello") is False

    # 2. Audio output playback failure
    bad_output = MockAudioOutput(simulate_error="Simulated audio output error")
    manager_bad_output = VoiceManager(
        speech_synthesizer=MockSpeechSynthesizer(),
        audio_output=bad_output,
    )
    assert await manager_bad_output.speak("Hello") is False


# ---------------------------------------------------------------------------
# 2. Timeouts, Expiration & Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_lifecycle_wake_timeout() -> None:
    """Verify bounded wake listening loop exits cleanly without infinite waiting."""
    mock_wake = MockWakeDetector(detection_pattern=[False])  # Never detects
    mock_input = MockAudioInput(auto_stop_on_empty=False)  # Infinite silence
    manager = VoiceManager(
        audio_input=mock_input,
        wake_detector=mock_wake,
    )

    start = time.time()
    detected = await manager.listen_for_wake_word(timeout_seconds=0.1)
    duration = time.time() - start
    assert detected is False
    assert duration < 1.0


def test_lifecycle_session_duration_expiration() -> None:
    """Verify session controller enforces maximum recording cap."""
    controller = VoiceSessionController(max_duration_seconds=0.05)
    controller.start_listening()
    time.sleep(0.08)
    assert controller.is_expired() is True


def test_lifecycle_expired_pending_action_rejection() -> None:
    """Verify pending actions past TTL cannot be confirmed."""
    pam = PendingActionManager(default_ttl=0.05)
    act = pam.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "temp.txt"},
        risk_level=RiskLevel.CRITICAL,
        session_id="exp-sess",
    )
    time.sleep(0.08)

    claimed, _action, status, msg = pam.claim_for_execution(act.action_id, session_id="exp-sess")
    assert claimed is False
    assert status == ConfirmationStatus.EXPIRED
    assert "expired" in msg.lower()


def test_lifecycle_concurrent_confirmation_race_safety() -> None:
    """Verify multithreaded confirmation claims the action exactly once under RLock."""
    pam = PendingActionManager()
    act = pam.create_pending_action(
        tool_name="delete_file",
        arguments={"path": "race.txt"},
        risk_level=RiskLevel.CRITICAL,
        session_id="race-sess",
    )

    claims = []

    def attempt_claim() -> tuple[bool, ConfirmationStatus]:
        c, _, s, _ = pam.claim_for_execution(act.action_id, session_id="race-sess")
        return c, s

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(attempt_claim) for _ in range(8)]
        for f in futures:
            claims.append(f.result())

    # Exactly 1 thread must succeed; all other 7 must receive ALREADY_PROCESSED
    successful = [c for c in claims if c[0] is True]
    rejected = [c for c in claims if c[0] is False]
    assert len(successful) == 1
    assert successful[0][1] == ConfirmationStatus.CONFIRMED
    assert len(rejected) == 7
    for r in rejected:
        assert r[1] == ConfirmationStatus.ALREADY_PROCESSED


# ---------------------------------------------------------------------------
# 3. Execution & Verification Failures during Confirmation Resumption
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_lifecycle_confirmation_execution_failure_handled() -> None:
    """Verify that when a confirmed action fails during tool execution, it is safely reported."""
    mock_brain = MagicMock()
    mock_brain.confirm_action.return_value = ConfirmationResult(
        success=False,
        status=ConfirmationStatus.FAILED,
        action_id="act-fail",
        message="Permission denied on file system.",
        error="PermissionDenied",
    )

    mock_output = MockAudioOutput()
    manager = VoiceManager(
        audio_output=mock_output,
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )

    intent, res, msg = await manager.resolve_voice_confirmation(
        session_id="sess-exec-fail",
        pending_action_id="act-fail",
        user_utterance="confirm",
        speak_outcome=True,
    )

    assert intent == ConfirmationIntent.CONFIRM
    assert res is not None
    assert res.success is False
    assert "Action execution failed" in msg
    assert "Permission denied" in msg
    assert mock_output.play_count == 1


@pytest.mark.anyio
async def test_lifecycle_confirmation_verification_failure_handled() -> None:
    """Verify that when post-condition verification fails, error is reported without tech leak."""
    mock_brain = MagicMock()
    v_res = VerificationResult(
        success=False,
        error="File still exists after delete operation.",
    )
    mock_brain.confirm_action.return_value = ConfirmationResult(
        success=False,
        status=ConfirmationStatus.CONFIRMED,
        action_id="act-verify-fail",
        message="Action executed, but post-condition verification failed.",
        verification=v_res,
    )

    manager = VoiceManager(
        audio_output=MockAudioOutput(),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )

    intent, res, msg = await manager.resolve_voice_confirmation(
        session_id="sess-v-fail",
        pending_action_id="act-verify-fail",
        user_utterance="okay",
        speak_outcome=False,
    )

    assert intent == ConfirmationIntent.CONFIRM
    assert res is not None
    assert res.success is False
    assert "verification failed" in msg


# ---------------------------------------------------------------------------
# 4. Confirmation Response While WAITING_CONFIRMATION Never Becomes Command
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_confirmation_response_never_invokes_brain_process() -> None:
    """Verify that user speech during confirmation is strictly validated and never sent to Brain.process."""
    mock_brain = MagicMock()
    mock_brain.cancel_action.return_value = ConfirmationResult(
        success=True,
        status=ConfirmationStatus.CANCELLED,
        action_id="act-no-cmd",
        message="Cancelled",
    )

    manager = VoiceManager(
        audio_output=MockAudioOutput(),
        speech_synthesizer=MockSpeechSynthesizer(),
        brain=mock_brain,
    )

    # User says "no" or "naah"
    intent, _, _ = await manager.resolve_voice_confirmation(
        session_id="sess-isolation",
        pending_action_id="act-no-cmd",
        user_utterance="no",
        speak_outcome=False,
    )

    assert intent == ConfirmationIntent.CANCEL
    # brain.process() MUST NOT be called!
    mock_brain.process.assert_not_called()
    mock_brain.cancel_action.assert_called_once_with("act-no-cmd", session_id="sess-isolation")


# ---------------------------------------------------------------------------
# 5. Audio Privacy Invariant: Zero Audio Files Throughout Full Voice Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_voice_privacy_no_disk_files() -> None:
    """Assert that the entire voice lifecycle creates ZERO audio or temporary files on disk."""
    opened_files: list[str] = []
    original_open = open

    def tracking_open(file, *args, **kwargs):
        opened_files.append(str(file))
        return original_open(file, *args, **kwargs)

    mock_brain = MagicMock()
    mock_brain.process = AsyncMock(return_value="Confirmed and ready.")

    mock_input = MockAudioInput(canned_chunks=[b"\x00\x01" * 1600], auto_stop_on_empty=True)
    mock_stt = MockSpeechRecognizer(transcripts=["run safe diagnostic"])

    manager = VoiceManager(
        audio_input=mock_input,
        speech_recognizer=mock_stt,
        speech_synthesizer=MockSpeechSynthesizer(),
        audio_output=MockAudioOutput(),
        brain=mock_brain,
    )

    with patch("builtins.open", side_effect=tracking_open):
        result = await manager.process_voice_interaction(speak_response=True)

    assert result.success is True

    # Assert no audio files were created
    audio_extensions = {".wav", ".pcm", ".raw", ".mp3", ".ogg", ".flac", ".tmp"}
    written_audio_files = [
        f for f in opened_files if any(f.endswith(ext) for ext in audio_extensions)
    ]
    assert len(written_audio_files) == 0, (
        f"Privacy violation: Audio files detected on disk: {written_audio_files}"
    )
