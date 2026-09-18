"""ECHO Voice Interfaces (Phase 6).

Defines canonical interfaces, data contracts, and state models for voice
input, speech recognition, speech synthesis, and voice session management.
Voice acts strictly as an input/output boundary adapter into Project ECHO.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class VoiceSessionState(str, Enum):
    """Lifecycle states of an active voice interaction."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    COMPLETED = "completed"
    ERROR = "error"
    CLOSED = "closed"


@dataclass(frozen=True)
class AudioChunk:
    """In-memory representation of a single captured audio slice."""

    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # 16-bit PCM
    timestamp: float = field(default_factory=time.time)

    @property
    def duration_seconds(self) -> float:
        """Calculate duration of this chunk in seconds."""
        if not self.data or self.sample_rate <= 0 or self.sample_width <= 0 or self.channels <= 0:
            return 0.0
        bytes_per_second = self.sample_rate * self.channels * self.sample_width
        return len(self.data) / bytes_per_second


@dataclass
class RecognitionResult:
    """Structured result returned by a Speech-to-Text engine."""

    text: str = ""
    confidence: float | None = None
    language: str = "en"
    duration_seconds: float = 0.0
    is_empty: bool = False
    error: str | None = None


@dataclass
class VoiceSession:
    """Stateful voice session tracker."""

    session_id: str = field(default_factory=lambda: str(uuid4()))
    state: VoiceSessionState = VoiceSessionState.IDLE
    started_at: float = field(default_factory=time.time)
    max_duration_seconds: float = 15.0
    silence_threshold_seconds: float = 2.0
    transcription: str = ""
    error: str | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Seconds elapsed since session started."""
        return time.time() - self.started_at

    def is_expired(self) -> bool:
        """Check if session exceeded maximum allowed recording duration."""
        return self.elapsed_seconds >= self.max_duration_seconds


@dataclass
class VoiceProcessResult:
    """Final result of a voice capture and Brain cognitive execution cycle."""

    success: bool
    session_id: str
    transcription: str
    brain_response: str | None = None
    duration_seconds: float = 0.0
    state: VoiceSessionState = VoiceSessionState.COMPLETED
    error: str | None = None


class AudioInput(ABC):
    """Abstract interface for audio capture hardware or virtual streams."""

    @abstractmethod
    def start_recording(self, sample_rate: int = 16000, channels: int = 1) -> None:
        """Start audio recording buffer."""

    @abstractmethod
    def read_chunk(self, max_bytes: int | None = None) -> AudioChunk | None:
        """Read the next available audio chunk from the buffer."""

    @abstractmethod
    def stop_recording(self) -> bytes:
        """Stop audio recording and return the accumulated raw PCM bytes."""

    @property
    @abstractmethod
    def is_recording(self) -> bool:
        """Return True if currently capturing audio."""


class SpeechRecognizer(ABC):
    """Abstract interface for offline Speech-to-Text (STT) inference engines."""

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> RecognitionResult:
        """Transcribe raw audio bytes to text."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if model and runtime dependencies are available locally."""


class BaseVAD(ABC):
    """Abstract interface for Voice Activity Detection."""

    @abstractmethod
    def is_speech(self, chunk: bytes, sample_rate: int = 16000) -> bool:
        """Determine whether the audio chunk contains active speech."""

    @abstractmethod
    def reset(self) -> None:
        """Reset internal silence/energy trackers."""


@dataclass(frozen=True)
class SynthesizedAudio:
    """In-memory representation of synthesized speech audio."""

    data: bytes
    sample_rate: int = 22050
    channels: int = 1
    sample_width: int = 2  # 16-bit PCM
    duration_seconds: float = 0.0


class AudioOutput(ABC):
    """Abstract interface for audio playback hardware or virtual sinks."""

    @abstractmethod
    def play(self, audio_data: bytes, sample_rate: int = 16000, channels: int = 1) -> None:
        """Play raw PCM audio bytes through the output device."""

    @abstractmethod
    def stop(self) -> None:
        """Stop active audio playback immediately."""

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """Return True if currently outputting audio."""


class SpeechSynthesizer(ABC):
    """Abstract interface for offline Text-to-Speech (TTS) synthesis engines."""

    @abstractmethod
    def synthesize(self, text: str) -> SynthesizedAudio:
        """Synthesize plain text into in-memory PCM audio bytes."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if TTS engine and model weights are available locally."""


class WakeDetector(ABC):
    """Abstract interface for local wake detection mechanisms."""

    @abstractmethod
    def detect(self, chunk: bytes, sample_rate: int = 16000) -> bool:
        """Process an audio chunk and return True if a wake event is detected."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if wake detector model/dependencies are available locally."""

    @abstractmethod
    def reset(self) -> None:
        """Reset internal detector state and history."""
