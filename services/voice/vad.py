"""Voice Activity Detection (VAD) and Silence Bounding (Phase 6A).

Provides lightweight, modular, 100% offline silence and speech detection
without requiring heavy external runtime dependencies.
"""

import math
import struct

from packages.interfaces.voice import BaseVAD


class EnergyVAD(BaseVAD):
    """Energy-based Root Mean Square (RMS) Voice Activity Detector for 16-bit PCM."""

    def __init__(
        self,
        energy_threshold: float = 300.0,
        sample_rate: int = 16000,
        sample_width: int = 2,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.speech_detected = False
        self.consecutive_silent_seconds = 0.0

    @staticmethod
    def calculate_rms(chunk: bytes) -> float:
        """Calculate Root Mean Square (RMS) energy of 16-bit mono PCM bytes."""
        if not chunk or len(chunk) < 2:
            return 0.0

        num_samples = len(chunk) // 2
        # Unpack 16-bit signed little-endian integers
        fmt = f"<{num_samples}h"
        try:
            samples = struct.unpack(fmt, chunk[: num_samples * 2])
        except struct.error:
            return 0.0

        sum_squares = sum(s * s for s in samples)
        mean_square = sum_squares / num_samples
        return math.sqrt(mean_square)

    def is_speech(self, chunk: bytes, sample_rate: int = 16000) -> bool:
        """Determine if chunk contains speech based on RMS energy threshold."""
        rms = self.calculate_rms(chunk)
        chunk_duration = len(chunk) / (self.sample_rate * self.sample_width)

        if rms >= self.energy_threshold:
            self.speech_detected = True
            self.consecutive_silent_seconds = 0.0
            return True

        if self.speech_detected:
            self.consecutive_silent_seconds += chunk_duration

        return False

    def is_silence_timeout(self, max_silence_seconds: float = 1.5) -> bool:
        """Return True if speech was previously active and followed by trailing silence."""
        return self.speech_detected and (self.consecutive_silent_seconds >= max_silence_seconds)

    def reset(self) -> None:
        """Reset internal speech and silence trackers."""
        self.speech_detected = False
        self.consecutive_silent_seconds = 0.0


class MockVAD(BaseVAD):
    """Deterministic Mock VAD for offline testing."""

    def __init__(
        self,
        speech_pattern: list[bool] | None = None,
        default_speech: bool = True,
    ) -> None:
        self.speech_pattern = list(speech_pattern) if speech_pattern is not None else []
        self.default_speech = default_speech
        self.call_count = 0
        self.speech_detected = False
        self.silence_chunks = 0

    def is_speech(self, chunk: bytes, sample_rate: int = 16000) -> bool:
        """Return pre-configured or default speech indicator."""
        if self.call_count < len(self.speech_pattern):
            speech = self.speech_pattern[self.call_count]
        else:
            speech = self.default_speech
        self.call_count += 1

        if speech:
            self.speech_detected = True
            self.silence_chunks = 0
        elif self.speech_detected:
            self.silence_chunks += 1

        return speech

    def is_silence_timeout(self, max_silence_chunks: int = 3) -> bool:
        """Return True if silence chunks reached threshold."""
        return self.speech_detected and (self.silence_chunks >= max_silence_chunks)

    def reset(self) -> None:
        """Reset call counter and flags."""
        self.call_count = 0
        self.speech_detected = False
        self.silence_chunks = 0
