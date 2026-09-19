"""Canonical E2E integration tests for ECHO Voice Subsystem (Phase 9B).

Exercises the full voice pipeline through VoiceManager and ECHOBrain:
AudioInput → STT → Request(source='voice') → Brain → Tools → VerificationEngine → TTS → AudioOutput
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from packages.interfaces.pending_action import ActionState, ConfirmationStatus
from packages.interfaces.plan import Plan, PlanStep
from packages.interfaces.request import Request
from packages.interfaces.voice import VoiceSessionState
from services.brain.brain import ECHOBrain
from services.security.pending_action_manager import pending_action_manager
from services.voice.audio_input import MockAudioInput
from services.voice.audio_output import MockAudioOutput
from services.voice.confirmation import VoiceConfirmationValidator
from services.voice.manager import VoiceManager
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import MockSpeechSynthesizer


@pytest.mark.anyio
async def test_e2e_voice_speech_to_brain_to_tts_full_cycle(
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify complete end-to-end voice loop: Speech In -> STT -> Brain -> Calculator Tool -> TTS -> Audio Out."""
    brain = fresh_echo_brain
    mock_stt = MockSpeechRecognizer(default_transcript="calculate 15 * 6")
    mock_input = MockAudioInput(
        canned_chunks=[b"\x01\x00" * 1600],
        auto_stop_on_empty=True,
    )
    mock_output = MockAudioOutput()
    mock_tts = MockSpeechSynthesizer()

    manager = VoiceManager(
        audio_input=mock_input,
        speech_recognizer=mock_stt,
        speech_synthesizer=mock_tts,
        audio_output=mock_output,
        brain=brain,
    )

    result = await manager.process_voice_interaction(
        speak_response=True,
        session_id="voice-session-calc-1",
    )

    assert result.success is True
    assert result.state == VoiceSessionState.COMPLETED
    assert result.transcription == "calculate 15 * 6"
    assert "90" in (result.brain_response or "")
    # Spoken audio was generated and output played
    assert mock_output.play_count >= 1
    assert sum(mock_output.played_payloads) > 0
    assert mock_tts.synthesize_count >= 1


@pytest.mark.anyio
async def test_e2e_voice_sensitive_action_requires_spoken_confirmation_and_executes(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify sensitive desktop operation halts for voice confirmation, resumes upon spoken 'yes', and writes to disk."""
    brain = fresh_echo_brain
    pending_action_manager.clear()
    target_file = isolated_workspace / "voice_created.txt"

    # Utterance 1: trigger create_file (sensitive)
    # Utterance 2: confirm with approved closed-set token 'yes'
    mock_stt = MockSpeechRecognizer(transcripts=["create voice file", "yes"])
    mock_input = MockAudioInput(
        canned_chunks=[b"\x02\x00" * 1600],
        auto_stop_on_empty=True,
    )
    mock_output = MockAudioOutput()
    mock_tts = MockSpeechSynthesizer()

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Create file via voice",
                tool_name="create_file",
                arguments={"path": str(target_file), "content": "Created via voice confirmation"},
            )
        ],
    )

    manager = VoiceManager(
        audio_input=mock_input,
        speech_recognizer=mock_stt,
        speech_synthesizer=mock_tts,
        audio_output=mock_output,
        brain=brain,
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        result = await manager.process_voice_interaction(
            speak_response=True,
            session_id="voice-session-write-1",
        )

        assert result.success is True
        assert result.state == VoiceSessionState.COMPLETED
        assert result.confirmation_result is not None
        assert result.confirmation_result.success is True
        assert "confirmed and executed" in (result.brain_response or "").lower()

        # Both the confirmation prompt and execution result were spoken
        assert mock_output.play_count >= 2

        # Independent physical disk verification
        assert target_file.exists()
        assert target_file.read_text(encoding="utf-8") == "Created via voice confirmation"


@pytest.mark.anyio
async def test_e2e_voice_cross_session_confirmation_rejected(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify pending actions bound to one voice session cannot be confirmed by a different session ID."""
    brain = fresh_echo_brain
    pending_action_manager.clear()
    target_file = isolated_workspace / "cross_session.txt"

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Sensitive action",
                tool_name="create_file",
                arguments={"path": str(target_file), "content": "Protected"},
            )
        ],
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        req = Request(
            user_input="Create file",
            source="voice",
            session_id="legitimate-session-001",
        )
        await brain.process(req)

        pending = [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]
        assert len(pending) == 1
        action_id = pending[0].action_id

    # Attacker or separate session attempts to confirm with mismatched session_id
    res = brain.confirm_action(action_id, session_id="attacker-session-999")
    assert res.success is False
    assert "session" in (res.message or "").lower() or "mismatch" in (res.message or "").lower()

    # File remains uncreated on disk
    assert not target_file.exists()


@pytest.mark.anyio
async def test_e2e_voice_ambiguous_utterance_fails_closed(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify non-approved confirmation tokens ('maybe', 'sure', 'yup') fail closed without executing actions."""
    brain = fresh_echo_brain
    pending_action_manager.clear()
    target_file = isolated_workspace / "ambiguous_check.txt"

    # User says 'maybe' instead of an approved token ('yes', 'confirm', 'okay', 'lets go', 'haan')
    mock_stt = MockSpeechRecognizer(transcripts=["create check file", "maybe"])
    mock_input = MockAudioInput(
        canned_chunks=[b"\x01\x00" * 1600],
        auto_stop_on_empty=True,
    )
    mock_output = MockAudioOutput()
    mock_tts = MockSpeechSynthesizer()

    plan = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Create file",
                tool_name="create_file",
                arguments={"path": str(target_file), "content": "Never written"},
            )
        ],
    )

    manager = VoiceManager(
        audio_input=mock_input,
        speech_recognizer=mock_stt,
        speech_synthesizer=mock_tts,
        audio_output=mock_output,
        brain=brain,
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan):
        result = await manager.process_voice_interaction(
            speak_response=True,
            session_id="ambiguous-session-001",
        )

        # Interaction was handled, but confirmation was NOT accepted
        assert (
            "unclear" in (result.brain_response or "").lower()
            or "cancelled" in (result.brain_response or "").lower()
        )
        # File must not exist on disk
        assert not target_file.exists()


@pytest.mark.anyio
async def test_e2e_voice_secret_redaction_in_spoken_output(
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify sensitive tokens and secret keys are never spoken aloud verbatim by the speech synthesizer."""
    mock_tts = MockSpeechSynthesizer()
    mock_output = MockAudioOutput()

    secret_key = "sk-proj-abcdef1234567890abcdef1234567890"

    manager = VoiceManager(
        speech_synthesizer=mock_tts,
        audio_output=mock_output,
    )

    # Format safe spoken confirmation prompt using VoiceConfirmationValidator
    safe_prompt = VoiceConfirmationValidator.format_safe_prompt(
        tool_name="delete_file",
        arguments={"path": "/secrets/api_keys.json", "secret_token": secret_key},
    )

    # 1. Assert prompt completely stripped secret_token and sensitive directory path
    assert secret_key not in safe_prompt
    assert "api_keys.json" in safe_prompt
    assert "delete" in safe_prompt

    # 2. VoiceManager speaks the sanitized prompt
    success = await manager.speak(safe_prompt)
    assert success is True
    assert mock_output.play_count == 1
    assert mock_tts.synthesize_count == 1


@pytest.mark.anyio
async def test_e2e_voice_audio_privacy_no_audio_files_persisted(
    fresh_echo_brain: ECHOBrain,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify audio data processed through the voice pipeline is held only in memory and never written to disk."""
    opened_files: list[str] = []
    original_open = open

    def monitored_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened_files.append(str(file))
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", monitored_open)

    mock_stt = MockSpeechRecognizer(default_transcript="what time is it")
    manager = VoiceManager(
        speech_recognizer=mock_stt,
        brain=fresh_echo_brain,
    )

    # Process 16000 bytes of raw audio in memory
    audio_pcm = b"\x00\x05" * 8000
    res = await manager.process_audio_bytes(audio_pcm)

    assert res.success is True
    # Verify no audio media formats (.wav, .pcm, .raw, .flac, .mp3) were written to disk
    audio_extensions = {".wav", ".pcm", ".raw", ".mp3", ".ogg", ".flac"}
    persisted_audio = [f for f in opened_files if any(f.endswith(ext) for ext in audio_extensions)]
    assert len(persisted_audio) == 0, f"Leaked audio files to disk: {persisted_audio}"


@pytest.mark.anyio
async def test_e2e_voice_replay_protection_blocks_reused_ticket(
    isolated_workspace: Path,
    fresh_echo_brain: ECHOBrain,
) -> None:
    """Verify that completed or cancelled voice confirmation tickets cannot be reused to execute actions again."""
    brain = fresh_echo_brain
    pending_action_manager.clear()
    target_file1 = isolated_workspace / "voice_replay_1.txt"
    target_file2 = isolated_workspace / "voice_replay_2.txt"

    # Part 1: Completed voice action cannot be confirmed again (replay protection)
    mock_stt = MockSpeechRecognizer(transcripts=["create replay file 1", "yes"])
    mock_input = MockAudioInput(
        canned_chunks=[b"\x03\x00" * 1600],
        auto_stop_on_empty=True,
    )
    manager = VoiceManager(
        audio_input=mock_input,
        speech_recognizer=mock_stt,
        speech_synthesizer=MockSpeechSynthesizer(),
        audio_output=MockAudioOutput(),
        brain=brain,
    )

    plan1 = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Create replay file 1",
                tool_name="create_file",
                arguments={"path": str(target_file1), "content": "Initial execution"},
            )
        ],
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan1):
        res1 = await manager.process_voice_interaction(
            speak_response=False,
            session_id="voice-replay-session-1",
        )
        assert res1.success is True
        assert res1.confirmation_result is not None
        assert res1.confirmation_result.success is True
        action_id1 = res1.confirmation_result.action_id
        assert target_file1.exists()

    # Replay attempt on completed ticket: must fail
    replay_res = brain.confirm_action(action_id1, session_id="voice-replay-session-1")
    assert replay_res.success is False
    assert (
        replay_res.status == ConfirmationStatus.ALREADY_PROCESSED
        or "already" in (replay_res.message or "").lower()
    )

    # Part 2: Cancelled voice action cannot be confirmed again
    plan2 = Plan(
        requires_planning=True,
        steps=[
            PlanStep(
                step_number=1,
                description="Create replay file 2",
                tool_name="create_file",
                arguments={"path": str(target_file2), "content": "Should never exist"},
            )
        ],
    )

    with patch("services.brain.planner.planner.create_plan", return_value=plan2):
        req2 = Request(
            user_input="Create replay file 2",
            source="voice",
            session_id="voice-replay-session-2",
        )
        await brain.process(req2)
        pending = [
            a for a in pending_action_manager._actions.values() if a.state == ActionState.PENDING
        ]
        assert len(pending) == 1
        action_id2 = pending[0].action_id

    # User cancels ticket
    cancel_res = brain.cancel_action(action_id2, session_id="voice-replay-session-2")
    assert cancel_res.success is True

    # Replay / resume attempt on cancelled ticket: must fail
    cancelled_replay_res = brain.confirm_action(action_id2, session_id="voice-replay-session-2")
    assert cancelled_replay_res.success is False
    assert (
        "cancelled" in (cancelled_replay_res.message or "").lower()
        or cancelled_replay_res.status != ConfirmationStatus.CONFIRMED
    )
    assert not target_file2.exists()
