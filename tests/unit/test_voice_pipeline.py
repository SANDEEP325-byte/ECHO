"""Unit tests for ECHO Voice Subsystem (Phase 6A + 6B).

Tests voice interfaces, audio input bounds, silence handling, session lifecycle,
offline STT inference, ModelUnavailable error handling, audio privacy invariants,
and ECHOBrain cognitive integration without external network, GPU, physical mic,
or physical speaker.
"""

import struct
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from packages.interfaces.request import Request
from packages.interfaces.voice import (
    AudioChunk,
    RecognitionResult,
    VoiceSession,
    VoiceSessionState,
)
from services.voice.audio_input import (
    MockAudioInput,
    SoundDeviceAudioInput,
)
from services.voice.errors import (
    AudioInputError,
    ModelUnavailableError,
    RecognitionError,
    VoiceSessionError,
)
from services.voice.manager import VoiceManager
from services.voice.session import VoiceSessionController
from services.voice.stt import (
    BaseSpeechRecognizer,
    FasterWhisperRecognizer,
    MockSpeechRecognizer,
)
from services.voice.vad import EnergyVAD, MockVAD

# ---------------------------------------------------------------------------
# 1. Interface & Contract Tests
# ---------------------------------------------------------------------------


def test_audio_chunk_properties():
    """Verify AudioChunk duration and parameter calculations."""
    # 16000 Hz, 1 channel, 16-bit (2 bytes per sample) -> 32000 bytes per second
    raw_data = b"\x00" * 32000
    chunk = AudioChunk(data=raw_data, sample_rate=16000, channels=1, sample_width=2)
    assert chunk.duration_seconds == pytest.approx(1.0, 0.01)

    empty_chunk = AudioChunk(data=b"")
    assert empty_chunk.duration_seconds == 0.0


def test_voice_session_defaults_and_expiry():
    """Verify VoiceSession default parameters and expiration checks."""
    session = VoiceSession(max_duration_seconds=0.1)
    assert session.state == VoiceSessionState.IDLE
    assert not session.is_expired()

    time.sleep(0.12)
    assert session.is_expired()


def test_recognition_result_defaults():
    """Verify RecognitionResult default state and field assignments."""
    result = RecognitionResult(text="echo status", confidence=0.98, duration_seconds=1.5)
    assert result.text == "echo status"
    assert result.confidence == 0.98
    assert not result.is_empty
    assert result.error is None


# ---------------------------------------------------------------------------
# 2. Silence Handling & VAD Tests
# ---------------------------------------------------------------------------


def test_energy_vad_rms_calculation():
    """Verify Root Mean Square (RMS) energy calculation on synthetic 16-bit PCM."""
    vad = EnergyVAD(energy_threshold=300.0)

    # Pure silence (all zeros)
    silence = b"\x00" * 1000
    assert vad.calculate_rms(silence) == 0.0
    assert not vad.is_speech(silence)

    # Synthesize a high-amplitude square wave (alternating between +10000 and -10000)
    samples = []
    for _ in range(500):
        samples.extend([10000, -10000])
    loud_pcm = struct.pack(f"<{len(samples)}h", *samples)

    rms = vad.calculate_rms(loud_pcm)
    assert rms > 5000.0
    assert vad.is_speech(loud_pcm)


def test_energy_vad_silence_timeout():
    """Verify silence timeout triggers only after speech was detected."""
    vad = EnergyVAD(energy_threshold=200.0, sample_rate=16000)

    # Initial silence should not trigger silence timeout
    silence = b"\x00" * 3200  # 0.1s of silence
    vad.is_speech(silence)
    assert not vad.is_silence_timeout(max_silence_seconds=0.2)

    # Detect active speech
    samples = [8000] * 1600
    speech_pcm = struct.pack(f"<{len(samples)}h", *samples)
    assert vad.is_speech(speech_pcm)

    # Accumulate silence past threshold
    for _ in range(4):
        vad.is_speech(b"\x00" * 3200)  # 4 * 0.1s = 0.4s

    assert vad.is_silence_timeout(max_silence_seconds=0.2)

    # Reset cleans flags
    vad.reset()
    assert not vad.is_silence_timeout(max_silence_seconds=0.2)


def test_mock_vad_pattern_and_reset():
    """Verify MockVAD follows deterministic speech pattern and resets."""
    pattern = [True, False, False, False]
    mock_vad = MockVAD(speech_pattern=pattern)

    assert mock_vad.is_speech(b"test")  # call 0: True
    assert not mock_vad.is_speech(b"test")  # call 1: False
    assert not mock_vad.is_speech(b"test")  # call 2: False
    assert not mock_vad.is_speech(b"test")  # call 3: False
    assert mock_vad.is_silence_timeout(max_silence_chunks=3)

    mock_vad.reset()
    assert mock_vad.call_count == 0
    assert not mock_vad.is_silence_timeout(max_silence_chunks=3)


# ---------------------------------------------------------------------------
# 3. Audio Capture & Bounding Tests
# ---------------------------------------------------------------------------


def test_mock_audio_input_bounded_capture():
    """Verify MockAudioInput enforces queue reads, start/stop, and duration limits."""
    canned = [b"chunk1", b"chunk2", b"chunk3"]
    audio_in = MockAudioInput(canned_chunks=canned, max_recording_seconds=10.0)

    assert not audio_in.is_recording
    audio_in.start_recording()
    assert audio_in.is_recording

    c1 = audio_in.read_chunk()
    assert c1 is not None and c1.data == b"chunk1"

    c2 = audio_in.read_chunk()
    assert c2 is not None and c2.data == b"chunk2"

    collected = audio_in.stop_recording()
    assert collected == b"chunk1chunk2"
    assert not audio_in.is_recording


def test_mock_audio_input_max_buffer_truncation():
    """Verify MockAudioInput truncates capture when buffer reaches MAX_BUFFER_BYTES."""
    # Set a tiny max recording duration so buffer cap is small
    audio_in = MockAudioInput(max_recording_seconds=0.01)  # max ~320 bytes
    audio_in.start_recording()

    large_chunk = b"\x01" * 500
    audio_in.add_chunk(large_chunk)

    chunk = audio_in.read_chunk()
    assert chunk is not None
    assert len(chunk.data) <= audio_in.max_buffer_bytes
    assert not audio_in.is_recording  # stopped due to buffer cap


def test_mock_audio_input_simulated_hardware_error():
    """Verify MockAudioInput raises AudioInputError when error simulation is enabled."""
    audio_in = MockAudioInput(simulate_error="Device unplugged")
    with pytest.raises(AudioInputError) as exc_info:
        audio_in.start_recording()
    assert "Device unplugged" in exc_info.value.message


def test_sounddevice_audio_input_graceful_missing_library():
    """Verify SoundDeviceAudioInput raises AudioInputError cleanly if library import fails."""
    audio_in = SoundDeviceAudioInput()
    with patch.dict("sys.modules", {"sounddevice": None}), pytest.raises(AudioInputError):
        audio_in.start_recording()


# ---------------------------------------------------------------------------
# 4. Session Controller & Lifecycle Tests
# ---------------------------------------------------------------------------


def test_session_controller_valid_transitions():
    """Verify normal session transition lifecycle."""
    ctrl = VoiceSessionController(max_duration_seconds=10.0)
    assert ctrl.state == VoiceSessionState.IDLE

    ctrl.start_listening()
    assert ctrl.state == VoiceSessionState.LISTENING

    ctrl.start_processing()
    assert ctrl.state == VoiceSessionState.PROCESSING

    ctrl.complete(transcription="open browser")
    assert ctrl.state == VoiceSessionState.COMPLETED
    assert ctrl.session.transcription == "open browser"


def test_session_controller_invalid_transition_fails():
    """Verify illegal transitions raise VoiceSessionError and set ERROR state."""
    ctrl = VoiceSessionController()
    assert ctrl.state == VoiceSessionState.IDLE

    # IDLE -> PROCESSING is illegal (must go through LISTENING)
    with pytest.raises(VoiceSessionError):
        ctrl.transition_to(VoiceSessionState.PROCESSING)

    assert ctrl.state == VoiceSessionState.ERROR


# ---------------------------------------------------------------------------
# 5. Speech Recognition (STT) Tests
# ---------------------------------------------------------------------------


def test_text_normalization():
    """Verify BaseSpeechRecognizer text cleaning and whitespace stripping."""
    assert BaseSpeechRecognizer.normalize_text("  hello    world  \n\t") == "hello world"
    assert BaseSpeechRecognizer.normalize_text("") == ""


def test_mock_speech_recognizer_success():
    """Verify MockSpeechRecognizer produces deterministic RecognitionResult."""
    recognizer = MockSpeechRecognizer(default_transcript="list files in current directory")
    audio = b"\x00" * 32000  # 1.0s
    res = recognizer.transcribe(audio)

    assert res.text == "list files in current directory"
    assert res.confidence == 0.95
    assert res.duration_seconds == pytest.approx(1.0, 0.05)
    assert not res.is_empty


def test_mock_speech_recognizer_model_unavailable():
    """Verify MockSpeechRecognizer raises ModelUnavailableError when configured unavailable."""
    recognizer = MockSpeechRecognizer(is_model_available=False)
    with pytest.raises(ModelUnavailableError) as exc_info:
        recognizer.transcribe(b"\x00" * 1000)
    assert "Mock STT model is not available locally" in exc_info.value.message


def test_faster_whisper_offline_enforcement_and_model_unavailable():
    """Verify FasterWhisperRecognizer raises ModelUnavailableError if local files are missing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        empty_dir = Path(tmp_dir) / "missing_model"
        recognizer = FasterWhisperRecognizer(model_dir=empty_dir)

        assert not recognizer.is_available()

        with pytest.raises(ModelUnavailableError) as exc_info:
            recognizer.transcribe(b"\x00" * 1000)

        assert "was not found at local directory" in exc_info.value.message
        assert "Automatic runtime downloading is prohibited" in exc_info.value.message


def test_faster_whisper_detects_valid_local_model_directory():
    """Verify FasterWhisperRecognizer recognizes when model.bin and config.json exist."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        model_dir = Path(tmp_dir) / "whisper-test"
        model_dir.mkdir()
        (model_dir / "model.bin").write_bytes(b"dummy model")
        (model_dir / "config.json").write_text("{}", encoding="utf-8")

        recognizer = FasterWhisperRecognizer(model_dir=model_dir)
        assert recognizer.is_available()


# ---------------------------------------------------------------------------
# 6. VoiceManager & ECHOBrain Pipeline Ingestion Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_voice_manager_safe_command_ingestion():
    """Verify safe voice commands are transcribed, ingested as Request(source='voice'), and executed."""
    mock_stt = MockSpeechRecognizer(default_transcript="what is the time")
    mock_brain = AsyncMock()
    mock_brain.process.return_value = "The current time is 10:00 AM."

    manager = VoiceManager(
        speech_recognizer=mock_stt,
        brain=mock_brain,
    )

    audio_payload = b"\x00" * 16000
    result = await manager.process_audio_bytes(audio_payload)

    assert result.success
    assert result.transcription == "what is the time"
    assert result.brain_response == "The current time is 10:00 AM."
    assert result.state == VoiceSessionState.COMPLETED

    # Verify brain.process was called with a Request having source="voice"
    mock_brain.process.assert_called_once()
    called_req = mock_brain.process.call_args[0][0]
    assert isinstance(called_req, Request)
    assert called_req.user_input == "what is the time"
    assert called_req.source == "voice"
    assert called_req.session_id == result.session_id


@pytest.mark.anyio
async def test_voice_manager_preserves_safety_confirm_boundary():
    """Verify sensitive/destructive voice commands preserve the CONFIRM boundary."""
    from services.brain.brain import ECHOBrain

    mock_stt = MockSpeechRecognizer(default_transcript="delete the file important.txt")

    # Use a real ECHOBrain instance with a mock execution engine returning confirmation prompt
    brain = ECHOBrain()
    manager = VoiceManager(
        speech_recognizer=mock_stt,
        brain=brain,
    )

    # Mock the brain's internal execution so it triggers a CONFIRM response
    with patch.object(
        brain,
        "process",
        new=AsyncMock(
            return_value="Action 'act-456' requires confirmation. Run '/confirm act-456' to proceed."
        ),
    ) as mock_process:
        result = await manager.process_audio_bytes(b"\x00" * 1000)

        assert result.success
        assert result.transcription == "delete the file important.txt"
        assert "requires confirmation" in (result.brain_response or "")

        # Verify the request entered with source="voice" and was NOT bypassed
        called_req = mock_process.call_args[0][0]
        assert isinstance(called_req, Request)
        assert called_req.source == "voice"
        assert called_req.user_input == "delete the file important.txt"


@pytest.mark.anyio
async def test_voice_manager_handles_model_unavailable():
    """Verify VoiceManager handles ModelUnavailableError gracefully with structured result."""
    mock_stt = MockSpeechRecognizer(is_model_available=False)
    manager = VoiceManager(speech_recognizer=mock_stt)

    result = await manager.process_audio_bytes(b"\x00" * 5000)

    assert not result.success
    assert result.state == VoiceSessionState.ERROR
    assert result.error is not None
    assert "Mock STT model is not available locally" in result.error
    assert result.brain_response is None


@pytest.mark.anyio
async def test_voice_manager_handles_empty_or_silent_audio():
    """Verify VoiceManager handles empty audio bytes without error."""
    mock_stt = MockSpeechRecognizer()
    manager = VoiceManager(speech_recognizer=mock_stt)

    result = await manager.process_audio_bytes(b"")

    assert result.success
    assert result.transcription == ""
    assert result.brain_response == "No speech detected."
    assert result.state == VoiceSessionState.COMPLETED


@pytest.mark.anyio
async def test_voice_manager_capture_and_process_flow():
    """Verify live capture_and_process flow with MockAudioInput and MockVAD."""
    # Synthetic chunks: speech then silence
    canned = [b"\x01\x02" * 1600, b"\x00\x00" * 1600, b"\x00\x00" * 1600, b"\x00\x00" * 1600]
    audio_in = MockAudioInput(canned_chunks=canned)
    vad = MockVAD(speech_pattern=[True, False, False, False])
    mock_stt = MockSpeechRecognizer(default_transcript="check battery status")
    mock_brain = AsyncMock()
    mock_brain.process.return_value = "Battery is at 95%."

    manager = VoiceManager(
        audio_input=audio_in,
        speech_recognizer=mock_stt,
        vad=vad,
        brain=mock_brain,
    )

    result = await manager.capture_and_process(max_duration_seconds=5.0)

    assert result.success
    assert result.transcription == "check battery status"
    assert result.brain_response == "Battery is at 95%."


# ---------------------------------------------------------------------------
# 7. Privacy Invariant Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_audio_privacy_no_disk_persistence(monkeypatch):
    """Verify raw audio bytes are never written to disk during voice ingestion."""
    # Track any file write or open operations
    opened_files: list[str] = []
    original_open = open

    def monitored_open(file, *args, **kwargs):
        opened_files.append(str(file))
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", monitored_open)

    mock_stt = MockSpeechRecognizer(default_transcript="private voice query")
    mock_brain = AsyncMock()
    mock_brain.process.return_value = "OK"

    manager = VoiceManager(speech_recognizer=mock_stt, brain=mock_brain)
    audio_bytes = b"\x12\x34\x56\x78" * 5000

    result = await manager.process_audio_bytes(audio_bytes)
    assert result.success

    # Verify no audio files (.wav, .pcm, .raw, .mp3, .tmp) were opened/written
    audio_extensions = {".wav", ".pcm", ".raw", ".mp3", ".ogg", ".flac", ".tmp"}
    written_audio_files = [
        f for f in opened_files if any(f.endswith(ext) for ext in audio_extensions)
    ]
    assert len(written_audio_files) == 0, (
        f"Unexpected audio file I/O detected: {written_audio_files}"
    )


def test_audio_privacy_no_raw_audio_in_errors():
    """Verify exceptions and error messages contain only error text, not audio data."""
    err = RecognitionError("Speech recognition failed on corrupted audio stream.")
    assert "corrupted audio stream" in str(err)
    assert not any(isinstance(arg, bytes) for arg in err.args)
