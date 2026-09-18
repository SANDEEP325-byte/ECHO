"""Audio Output Drivers and Playback Abstractions (Phase 6C).

Provides hardware and synthetic audio playback capabilities with bounded payload
sizes, thread-safe playback tracking, and zero raw audio persistence.
"""

import threading

from packages.interfaces.voice import AudioOutput
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.voice.errors import AudioOutputError


class BaseAudioOutput(AudioOutput):
    """Base class for audio output devices with strict payload bounding."""

    MAX_OUTPUT_BYTES = 5 * 1024 * 1024  # 5 MB (~2.5 minutes of 16kHz 16-bit mono)

    def __init__(self, max_output_bytes: int = MAX_OUTPUT_BYTES) -> None:
        self.max_output_bytes = max_output_bytes
        self._is_playing = False
        self._lock = threading.RLock()

    @property
    def is_playing(self) -> bool:
        """Return True if currently outputting audio."""
        with self._lock:
            return self._is_playing


class MockAudioOutput(BaseAudioOutput):
    """Deterministic, 100% offline synthetic audio output for testing."""

    def __init__(
        self,
        max_output_bytes: int = BaseAudioOutput.MAX_OUTPUT_BYTES,
        simulate_error: str | None = None,
    ) -> None:
        super().__init__(max_output_bytes=max_output_bytes)
        self.simulate_error = simulate_error
        self.played_payloads: list[int] = []  # Lengths only, preserving audio privacy

    @property
    def play_count(self) -> int:
        """Total number of audio play calls simulated."""
        return len(self.played_payloads)

    def play(self, audio_data: bytes, sample_rate: int = 16000, channels: int = 1) -> None:
        """Simulate playing raw PCM audio bytes."""
        with self._lock:
            if self.simulate_error:
                raise AudioOutputError(f"Simulated audio output error: {self.simulate_error}")

            if len(audio_data) > self.max_output_bytes:
                raise AudioOutputError(
                    f"Audio payload ({len(audio_data)} bytes) exceeds maximum bound of {self.max_output_bytes} bytes."
                )

            self.played_payloads.append(len(audio_data))
            self._is_playing = True
            logger.info(
                "MockAudioOutput played %d bytes at %dHz (ch=%d)",
                len(audio_data),
                sample_rate,
                channels,
            )
            self._is_playing = False

    def stop(self) -> None:
        """Stop mock playback."""
        with self._lock:
            self._is_playing = False
            logger.info("MockAudioOutput playback stopped.")


class SoundDeviceAudioOutput(BaseAudioOutput):
    """Hardware audio playback driver wrapping the sounddevice library."""

    def __init__(self, max_output_bytes: int = BaseAudioOutput.MAX_OUTPUT_BYTES) -> None:
        super().__init__(max_output_bytes=max_output_bytes)

    def play(self, audio_data: bytes, sample_rate: int = 16000, channels: int = 1) -> None:
        """Play raw 16-bit signed PCM mono/stereo audio bytes through system speaker."""
        with self._lock:
            if not audio_data:
                return

            if len(audio_data) > self.max_output_bytes:
                raise AudioOutputError(
                    f"Audio payload ({len(audio_data)} bytes) exceeds maximum bound of {self.max_output_bytes} bytes."
                )

            try:
                import sounddevice as sd  # type: ignore[import-untyped]
            except ImportError as err:
                raise AudioOutputError(
                    "sounddevice library is not installed or audio hardware is unavailable."
                ) from err

            import numpy as np

            try:
                # Convert 16-bit PCM bytes to numpy array
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                self._is_playing = True
                logger.info(
                    "SoundDevice playing %d audio samples at %dHz", len(audio_array), sample_rate
                )
                sd.play(audio_array, samplerate=sample_rate, blocking=True)
            except Exception as exc:
                raise AudioOutputError(f"Failed to play audio through sounddevice: {exc}") from exc
            finally:
                self._is_playing = False

    def stop(self) -> None:
        """Halt any active sounddevice playback."""
        with self._lock:
            try:
                import sounddevice as sd

                sd.stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error stopping sounddevice playback: %s", exc)
            finally:
                self._is_playing = False
                logger.info("SoundDevice playback stopped.")
