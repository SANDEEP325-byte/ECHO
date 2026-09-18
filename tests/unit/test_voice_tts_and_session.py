"""Unit tests for ECHO Voice Subsystem Phase 6C & Phase 6D.

Tests TTS synthesis, audio playback, session state machine, wake detection,
privacy invariants, error handling, and end-to-end vocal responses without
external network, GPU, physical microphone, or physical speaker.
"""

import struct
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from packages.interfaces.request import Request
from packages.interfaces.voice import SynthesizedAudio, VoiceSessionState
from services.voice.audio_input import MockAudioInput
from services.voice.audio_output import MockAudioOutput, SoundDeviceAudioOutput
from services.voice.errors import (
    AudioOutputError,
    ModelUnavailableError,
    SynthesisError,
    VoiceSessionError,
    WakeDetectionError,
)
from services.voice.manager import VoiceManager
from services.voice.session import VoiceSessionController
from services.voice.stt import MockSpeechRecognizer
from services.voice.tts import (
    BaseSpeechSynthesizer,
    LocalSpeechSynthesizer,
    MockSpeechSynthesizer,
)
from services.voice.wake import (
    LocalEnergyWakeDetector,
    MockWakeDetector,
    OpenWakeWordDetector,
)

# ---------------------------------------------------------------------------
# 1. TTS Interface & Synthesizer Tests (Phase 6C)
# ---------------------------------------------------------------------------


def test_synthesized_audio_properties():
    """Verify SynthesizedAudio dataclass fields and defaults."""
    audio = SynthesizedAudio(data=b"\x00" * 44100, sample_rate=22050, duration_seconds=1.0)
    assert len(audio.data) == 44100
    assert audio.sample_rate == 22050
    assert audio.duration_seconds == 1.0
    assert audio.channels == 1
    assert audio.sample_width == 2


def test_speech_synthesizer_text_cleaning_and_bounds():
    """Verify BaseSpeechSynthesizer sanitizes whitespace and truncates oversized text."""
    dirty_text = "   Hello \n\t  ECHO   "
    assert BaseSpeechSynthesizer.clean_text(dirty_text) == "Hello ECHO"

    # Enforce maximum text length bound
    huge_text = "a" * (BaseSpeechSynthesizer.MAX_TEXT_LENGTH + 500)
    cleaned = BaseSpeechSynthesizer.clean_text(huge_text)
    assert len(cleaned) == BaseSpeechSynthesizer.MAX_TEXT_LENGTH


def test_mock_speech_synthesizer_success():
    """Verify MockSpeechSynthesizer generates deterministic in-memory audio."""
    synth = MockSpeechSynthesizer()
    audio = synth.synthesize("Status update: all systems nominal.")

    assert len(audio.data) > 0
    assert audio.duration_seconds > 0.0
    assert audio.sample_rate == BaseSpeechSynthesizer.DEFAULT_SAMPLE_RATE
    assert len(synth.synthesized_calls) == 1

    # Empty text handling
    empty_audio = synth.synthesize("")
    assert empty_audio.data == b""
    assert empty_audio.duration_seconds == 0.0


def test_mock_speech_synthesizer_model_unavailable():
    """Verify MockSpeechSynthesizer raises ModelUnavailableError when unavailable."""
    synth = MockSpeechSynthesizer(is_model_available=False)
    with pytest.raises(ModelUnavailableError) as exc_info:
        synth.synthesize("Hello")
    assert "Automatic runtime downloads are prohibited" in exc_info.value.message


def test_mock_speech_synthesizer_simulated_error():
    """Verify MockSpeechSynthesizer raises SynthesisError when error simulation is enabled."""
    synth = MockSpeechSynthesizer(simulate_error="Internal DSP buffer overflow")
    with pytest.raises(SynthesisError) as exc_info:
        synth.synthesize("Hello")
    assert "Internal DSP buffer overflow" in exc_info.value.message


def test_local_speech_synthesizer_offline_model_unavailable():
    """Verify LocalSpeechSynthesizer raises ModelUnavailableError if local models are missing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        missing_dir = Path(tmp_dir) / "missing_voice"
        synth = LocalSpeechSynthesizer(model_dir=missing_dir, voice_name="nonexistent")

        # Mock SAPI5 dispatch failure to ensure clean offline check
        with patch.dict("sys.modules", {"win32com.client": None}):
            assert not synth.is_available()
            with pytest.raises(ModelUnavailableError) as exc_info:
                synth.synthesize("System check.")
            assert "Automatic runtime downloads are prohibited" in exc_info.value.message


# ---------------------------------------------------------------------------
# 2. Audio Playback & Output Tests (Phase 6C)
# ---------------------------------------------------------------------------


def test_mock_audio_output_play_and_bounds():
    """Verify MockAudioOutput plays in-memory audio and enforces byte limits."""
    output = MockAudioOutput(max_output_bytes=1000)

    assert not output.is_playing
    output.play(b"\x00" * 500, sample_rate=16000)
    assert len(output.played_payloads) == 1
    assert output.played_payloads[0] == 500

    # Oversized payload rejection
    with pytest.raises(AudioOutputError) as exc_info:
        output.play(b"\x00" * 1500)
    assert "exceeds maximum bound" in exc_info.value.message


def test_mock_audio_output_simulated_error():
    """Verify MockAudioOutput raises AudioOutputError on simulated failure."""
    output = MockAudioOutput(simulate_error="Hardware DAC disconnected")
    with pytest.raises(AudioOutputError) as exc_info:
        output.play(b"\x00" * 100)
    assert "Hardware DAC disconnected" in exc_info.value.message


def test_sounddevice_audio_output_missing_library():
    """Verify SoundDeviceAudioOutput cleanly catches missing sounddevice library."""
    output = SoundDeviceAudioOutput()
    with patch.dict("sys.modules", {"sounddevice": None}), pytest.raises(AudioOutputError):
        output.play(b"\x00" * 100)


# ---------------------------------------------------------------------------
# 3. Voice Session State Machine Tests (Phase 6D)
# ---------------------------------------------------------------------------


def test_session_controller_full_state_transitions():
    """Verify complete valid state transition lifecycle."""
    ctrl = VoiceSessionController(max_duration_seconds=10.0, idle_timeout_seconds=5.0)
    assert ctrl.state == VoiceSessionState.IDLE

    # IDLE -> LISTENING -> PROCESSING -> SPEAKING -> COMPLETED -> CLOSED
    ctrl.start_listening()
    assert ctrl.state == VoiceSessionState.LISTENING

    ctrl.start_processing()
    assert ctrl.state == VoiceSessionState.PROCESSING

    ctrl.start_speaking()
    assert ctrl.state == VoiceSessionState.SPEAKING

    ctrl.complete(transcription="test query")
    assert ctrl.state == VoiceSessionState.COMPLETED

    ctrl.close()
    assert ctrl.state == VoiceSessionState.CLOSED


def test_session_controller_silence_idle_reset():
    """Verify LISTENING can return to IDLE on silence/no-speech timeout."""
    ctrl = VoiceSessionController()
    ctrl.start_listening()
    assert ctrl.state == VoiceSessionState.LISTENING

    ctrl.transition_to(VoiceSessionState.IDLE)
    assert ctrl.state == VoiceSessionState.IDLE


def test_session_controller_invalid_transitions():
    """Verify illegal transitions raise VoiceSessionError and set ERROR state."""
    ctrl = VoiceSessionController()

    # IDLE -> PROCESSING is illegal (must go through LISTENING)
    with pytest.raises(VoiceSessionError):
        ctrl.transition_to(VoiceSessionState.PROCESSING)
    assert ctrl.state == VoiceSessionState.ERROR


def test_session_controller_idle_timeout():
    """Verify idle timeout detection."""
    ctrl = VoiceSessionController(idle_timeout_seconds=0.1)
    assert not ctrl.is_idle_timed_out()

    time.sleep(0.12)
    assert ctrl.is_idle_timed_out()

    ctrl.reset()
    assert not ctrl.is_idle_timed_out()
    assert ctrl.state == VoiceSessionState.IDLE


# ---------------------------------------------------------------------------
# 4. Wake Mechanism Tests (Phase 6D)
# ---------------------------------------------------------------------------


def test_mock_wake_detector_pattern():
    """Verify MockWakeDetector reports detections according to configured pattern."""
    detector = MockWakeDetector(detection_pattern=[False, False, True, False])
    assert detector.is_available()

    assert not detector.detect(b"chunk1")
    assert not detector.detect(b"chunk2")
    assert detector.detect(b"chunk3")
    assert not detector.detect(b"chunk4")
    assert not detector.detect(b"chunk5")  # beyond pattern defaults to False

    detector.reset()
    assert detector.call_count == 0


def test_mock_wake_detector_unavailable_and_error():
    """Verify MockWakeDetector error and availability handling."""
    unavail = MockWakeDetector(is_available=False)
    with pytest.raises(ModelUnavailableError):
        unavail.detect(b"chunk")

    err_det = MockWakeDetector(simulate_error="Wake model corrupt")
    with pytest.raises(WakeDetectionError):
        err_det.detect(b"chunk")


def test_local_energy_wake_detector_activity_trigger():
    """Verify LocalEnergyWakeDetector triggers strictly on acoustic energy burst."""
    detector = LocalEnergyWakeDetector(energy_threshold=1000.0)
    assert detector.is_available()

    # Pure silence
    silence = b"\x00" * 3200
    assert not detector.detect(silence)

    # High-amplitude square wave (loud acoustic event)
    samples = [8000, -8000] * 500
    loud_pcm = struct.pack(f"<{len(samples)}h", *samples)
    assert detector.detect(loud_pcm)


def test_open_wake_word_detector_missing_model():
    """Verify OpenWakeWordDetector raises ModelUnavailableError if model is missing."""
    detector = OpenWakeWordDetector(model_path="nonexistent_model.onnx")
    assert not detector.is_available()

    with pytest.raises(ModelUnavailableError) as exc_info:
        detector.detect(b"\x00" * 1000)
    assert "Automatic runtime downloads are prohibited" in exc_info.value.message


# ---------------------------------------------------------------------------
# 5. VoiceManager TTS & Playback Integration Tests (Phase 6C + 6D)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_voice_manager_speak_success():
    """Verify VoiceManager.speak synthesizes text and plays audio in-memory."""
    mock_synth = MockSpeechSynthesizer()
    mock_out = MockAudioOutput()

    manager = VoiceManager(
        speech_synthesizer=mock_synth,
        audio_output=mock_out,
    )

    success = await manager.speak("Echo system online.")
    assert success
    assert len(mock_synth.synthesized_calls) == 1
    assert len(mock_out.played_payloads) == 1

    # Empty text handling
    assert not await manager.speak("")


@pytest.mark.anyio
async def test_voice_manager_speak_handles_tts_failure_gracefully():
    """Verify VoiceManager.speak handles synthesis failures without crashing."""
    failing_synth = MockSpeechSynthesizer(simulate_error="DSP failure")
    mock_out = MockAudioOutput()

    manager = VoiceManager(
        speech_synthesizer=failing_synth,
        audio_output=mock_out,
    )

    success = await manager.speak("Will fail.")
    assert not success
    assert len(mock_out.played_payloads) == 0


@pytest.mark.anyio
async def test_voice_manager_speak_handles_playback_failure_gracefully():
    """Verify VoiceManager.speak handles playback failures without crashing."""
    mock_synth = MockSpeechSynthesizer()
    failing_out = MockAudioOutput(simulate_error="Speaker device lost")

    manager = VoiceManager(
        speech_synthesizer=mock_synth,
        audio_output=failing_out,
    )

    success = await manager.speak("Play audio.")
    assert not success


# ---------------------------------------------------------------------------
# 6. VoiceManager Wake Word Integration Tests (Phase 6D)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_voice_manager_listen_for_wake_word_detected():
    """Verify listen_for_wake_word detects wake event and stops capture."""
    canned = [b"\x00" * 1600, b"\x00" * 1600, b"\x00" * 1600]
    audio_in = MockAudioInput(canned_chunks=canned)
    wake_det = MockWakeDetector(detection_pattern=[False, True, False])

    manager = VoiceManager(
        audio_input=audio_in,
        wake_detector=wake_det,
    )

    detected = await manager.listen_for_wake_word(timeout_seconds=5.0)
    assert detected
    assert not audio_in.is_recording  # Audio capture stopped upon detection


@pytest.mark.anyio
async def test_voice_manager_listen_for_wake_word_timeout():
    """Verify listen_for_wake_word returns False upon timeout."""
    canned = [b"\x00" * 1600]
    audio_in = MockAudioInput(canned_chunks=canned)
    wake_det = MockWakeDetector(detection_pattern=[False])

    manager = VoiceManager(
        audio_input=audio_in,
        wake_detector=wake_det,
    )

    detected = await manager.listen_for_wake_word(timeout_seconds=0.05)
    assert not detected
    assert not audio_in.is_recording


# ---------------------------------------------------------------------------
# 7. End-to-End Voice Interaction & Privacy Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_voice_manager_process_voice_interaction_end_to_end():
    """Verify full interaction: capture -> STT -> Brain execution -> TTS output."""
    canned = [b"\x01\x02" * 1600, b"\x00\x00" * 1600, b"\x00\x00" * 1600, b"\x00\x00" * 1600]
    audio_in = MockAudioInput(canned_chunks=canned, auto_stop_on_empty=True)
    mock_stt = MockSpeechRecognizer(default_transcript="what is the weather today")
    mock_synth = MockSpeechSynthesizer()
    mock_out = MockAudioOutput()
    mock_brain = AsyncMock()
    mock_brain.process.return_value = "The weather is sunny with a high of 24 degrees."

    manager = VoiceManager(
        audio_input=audio_in,
        speech_recognizer=mock_stt,
        audio_output=mock_out,
        speech_synthesizer=mock_synth,
        brain=mock_brain,
    )

    result = await manager.process_voice_interaction(speak_response=True)

    assert result.success
    assert result.transcription == "what is the weather today"
    assert result.brain_response == "The weather is sunny with a high of 24 degrees."

    # Verify TTS synthesis and audio playback were invoked for the brain response
    assert len(mock_synth.synthesized_calls) == 1
    assert len(mock_out.played_payloads) == 1

    # Verify canonical Request structure passed to brain
    called_req = mock_brain.process.call_args[0][0]
    assert isinstance(called_req, Request)
    assert called_req.source == "voice"
    assert called_req.user_input == "what is the weather today"


@pytest.mark.anyio
async def test_tts_audio_privacy_no_disk_files(monkeypatch):
    """Verify TTS and audio playback never create temporary or permanent disk files."""
    opened_files: list[str] = []
    original_open = open

    def monitored_open(file, *args, **kwargs):
        opened_files.append(str(file))
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", monitored_open)

    mock_synth = MockSpeechSynthesizer()
    mock_out = MockAudioOutput()
    manager = VoiceManager(speech_synthesizer=mock_synth, audio_output=mock_out)

    success = await manager.speak("Testing strict audio privacy invariants.")
    assert success

    # Verify no audio files (.wav, .pcm, .raw, .mp3, .tmp) were opened/written
    audio_extensions = {".wav", ".pcm", ".raw", ".mp3", ".ogg", ".flac", ".tmp"}
    written_audio_files = [
        f for f in opened_files if any(f.endswith(ext) for ext in audio_extensions)
    ]
    assert len(written_audio_files) == 0, (
        f"Unexpected audio file I/O detected: {written_audio_files}"
    )
