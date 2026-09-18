"""Project ECHO Voice Subsystem (Phase 6).

Provides modular, privacy-first, 100% offline Speech-to-Text (STT), Text-to-Speech (TTS),
audio capture/playback, and wake detection services.
Operates strictly as an input/output boundary adapter into Project ECHO.
"""

from packages.interfaces.voice import (
    AudioChunk,
    AudioInput,
    AudioOutput,
    BaseVAD,
    RecognitionResult,
    SpeechRecognizer,
    SpeechSynthesizer,
    SynthesizedAudio,
    VoiceProcessResult,
    VoiceSession,
    VoiceSessionState,
    WakeDetector,
)
from services.voice.audio_input import (
    BaseAudioInput,
    MockAudioInput,
    SoundDeviceAudioInput,
)
from services.voice.audio_output import (
    BaseAudioOutput,
    MockAudioOutput,
    SoundDeviceAudioOutput,
)
from services.voice.confirmation import (
    ConfirmationIntent,
    VoiceConfirmationValidator,
)
from services.voice.errors import (
    AudioInputError,
    AudioOutputError,
    ModelUnavailableError,
    RecognitionError,
    SynthesisError,
    VoiceError,
    VoiceSessionError,
    WakeDetectionError,
)
from services.voice.manager import VoiceManager, voice_manager
from services.voice.session import VoiceSessionController
from services.voice.stt import (
    BaseSpeechRecognizer,
    FasterWhisperRecognizer,
    MockSpeechRecognizer,
)
from services.voice.tts import (
    BaseSpeechSynthesizer,
    LocalSpeechSynthesizer,
    MockSpeechSynthesizer,
)
from services.voice.vad import EnergyVAD, MockVAD
from services.voice.wake import (
    BaseWakeDetector,
    LocalEnergyWakeDetector,
    MockWakeDetector,
    OpenWakeWordDetector,
)

__all__ = [
    "AudioChunk",
    "AudioInput",
    "AudioInputError",
    "AudioOutput",
    "AudioOutputError",
    "BaseAudioInput",
    "BaseAudioOutput",
    "BaseSpeechRecognizer",
    "BaseSpeechSynthesizer",
    "BaseVAD",
    "BaseWakeDetector",
    "ConfirmationIntent",
    "EnergyVAD",
    "FasterWhisperRecognizer",
    "LocalEnergyWakeDetector",
    "LocalSpeechSynthesizer",
    "MockAudioInput",
    "MockAudioOutput",
    "MockSpeechRecognizer",
    "MockSpeechSynthesizer",
    "MockVAD",
    "MockWakeDetector",
    "ModelUnavailableError",
    "OpenWakeWordDetector",
    "RecognitionError",
    "RecognitionResult",
    "SoundDeviceAudioInput",
    "SoundDeviceAudioOutput",
    "SpeechRecognizer",
    "SpeechSynthesizer",
    "SynthesisError",
    "SynthesizedAudio",
    "VoiceConfirmationValidator",
    "VoiceError",
    "VoiceManager",
    "VoiceProcessResult",
    "VoiceSession",
    "VoiceSessionController",
    "VoiceSessionError",
    "VoiceSessionState",
    "WakeDetectionError",
    "WakeDetector",
    "voice_manager",
]
