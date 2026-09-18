"""Project ECHO Voice Subsystem (Phase 6).

Provides modular, privacy-first, 100% offline Speech-to-Text (STT) and voice
capture services. Operates strictly as an input/output boundary adapter.
"""

from packages.interfaces.voice import (
    AudioChunk,
    AudioInput,
    BaseVAD,
    RecognitionResult,
    SpeechRecognizer,
    VoiceProcessResult,
    VoiceSession,
    VoiceSessionState,
)
from services.voice.audio_input import (
    BaseAudioInput,
    MockAudioInput,
    SoundDeviceAudioInput,
)
from services.voice.errors import (
    AudioInputError,
    ModelUnavailableError,
    RecognitionError,
    VoiceError,
    VoiceSessionError,
)
from services.voice.manager import VoiceManager, voice_manager
from services.voice.session import VoiceSessionController
from services.voice.stt import (
    BaseSpeechRecognizer,
    FasterWhisperRecognizer,
    MockSpeechRecognizer,
)
from services.voice.vad import EnergyVAD, MockVAD

__all__ = [
    "AudioChunk",
    "AudioInput",
    "AudioInputError",
    "BaseAudioInput",
    "BaseSpeechRecognizer",
    "BaseVAD",
    "EnergyVAD",
    "FasterWhisperRecognizer",
    "MockAudioInput",
    "MockSpeechRecognizer",
    "MockVAD",
    "ModelUnavailableError",
    "RecognitionError",
    "RecognitionResult",
    "SoundDeviceAudioInput",
    "SpeechRecognizer",
    "VoiceError",
    "VoiceManager",
    "VoiceProcessResult",
    "VoiceSession",
    "VoiceSessionController",
    "VoiceSessionError",
    "VoiceSessionState",
    "voice_manager",
]
