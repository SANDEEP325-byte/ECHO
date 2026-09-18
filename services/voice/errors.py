"""ECHO Voice Exceptions (Phase 6).

Defines custom, structured exception types for voice audio capture,
offline STT inference, local model availability, and session lifecycle.
"""


class VoiceError(Exception):
    """Base exception for all voice subsystem errors."""

    def __init__(self, message: str, details: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class AudioInputError(VoiceError):
    """Raised when audio capture fails or device is inaccessible."""


class ModelUnavailableError(VoiceError):
    """Raised when an STT model is not available locally.

    Automatic runtime downloading is prohibited by ECHO's privacy
    and security invariants. Models must be provisioned ahead of time.
    """


class RecognitionError(VoiceError):
    """Raised when Speech-to-Text inference fails on audio data."""


class VoiceSessionError(VoiceError):
    """Raised when an invalid state transition or session timeout occurs."""


class AudioOutputError(VoiceError):
    """Raised when audio playback fails or device is inaccessible."""


class SynthesisError(VoiceError):
    """Raised when Text-to-Speech synthesis fails on input text."""


class WakeDetectionError(VoiceError):
    """Raised when wake event detection fails."""
