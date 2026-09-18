"""Audio Input Hardware and Synthetic Drivers (Phase 6A).

Provides modular audio capture abstractions with strict bounded recording,
buffer size limits, and 100% deterministic offline mock implementations.
"""

import threading
import time
from collections import deque
from typing import Any

from packages.interfaces.voice import AudioChunk, AudioInput
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.voice.errors import AudioInputError


class BaseAudioInput(AudioInput):
    """Base class providing buffer bounds and duration protection for audio inputs."""

    DEFAULT_SAMPLE_RATE = 16000
    DEFAULT_CHANNELS = 1
    DEFAULT_SAMPLE_WIDTH = 2  # 16-bit PCM

    MAX_RECORDING_SECONDS = 15.0
    MAX_BUFFER_BYTES = int(
        DEFAULT_SAMPLE_RATE * DEFAULT_SAMPLE_WIDTH * MAX_RECORDING_SECONDS
    )  # 480 KB

    def __init__(self, max_recording_seconds: float = MAX_RECORDING_SECONDS) -> None:
        self.max_recording_seconds = min(max_recording_seconds, 30.0)
        self.max_buffer_bytes = int(
            self.DEFAULT_SAMPLE_RATE * self.DEFAULT_SAMPLE_WIDTH * self.max_recording_seconds
        )
        self._is_recording = False
        self._start_time = 0.0
        self._lock = threading.RLock()

    @property
    def is_recording(self) -> bool:
        """Return True if capture is currently active."""
        with self._lock:
            if not self._is_recording:
                return False
            # Automatically enforce hard duration cap
            if (time.time() - self._start_time) >= self.max_recording_seconds:
                logger.warning(
                    "Audio recording reached hard timeout of %.1fs; capping capture.",
                    self.max_recording_seconds,
                )
                return False
            return True


class MockAudioInput(BaseAudioInput):
    """Deterministic, 100% offline synthetic audio feeder for testing."""

    def __init__(
        self,
        canned_chunks: list[bytes] | None = None,
        max_recording_seconds: float = BaseAudioInput.MAX_RECORDING_SECONDS,
        simulate_error: str | None = None,
    ) -> None:
        super().__init__(max_recording_seconds=max_recording_seconds)
        self._canned_chunks = list(canned_chunks) if canned_chunks is not None else []
        self._queue: deque[bytes] = deque()
        self._collected_bytes = bytearray()
        self._simulate_error = simulate_error

    def add_chunk(self, chunk: bytes) -> None:
        """Enqueue an audio chunk to be yielded by read_chunk."""
        with self._lock:
            self._queue.append(chunk)

    def start_recording(self, sample_rate: int = 16000, channels: int = 1) -> None:
        """Start synthetic recording."""
        with self._lock:
            if self._simulate_error:
                raise AudioInputError(f"Simulated audio device error: {self._simulate_error}")

            self._is_recording = True
            self._start_time = time.time()
            self._collected_bytes.clear()
            self._queue = deque(self._canned_chunks)
            logger.info(
                "MockAudioInput recording started (sample_rate=%d, channels=%d)",
                sample_rate,
                channels,
            )

    def read_chunk(self, max_bytes: int | None = None) -> AudioChunk | None:
        """Read the next canned chunk from the synthetic queue."""
        with self._lock:
            if not self.is_recording:
                return None

            if not self._queue:
                return None

            chunk_data = self._queue.popleft()
            if max_bytes and len(chunk_data) > max_bytes:
                remaining = chunk_data[max_bytes:]
                chunk_data = chunk_data[:max_bytes]
                self._queue.appendleft(remaining)

            # Check buffer size bounds
            if len(self._collected_bytes) + len(chunk_data) > self.max_buffer_bytes:
                excess = (len(self._collected_bytes) + len(chunk_data)) - self.max_buffer_bytes
                chunk_data = chunk_data[:-excess]
                self._is_recording = False
                logger.warning("MockAudioInput buffer exceeded max bound; truncated capture.")

            self._collected_bytes.extend(chunk_data)
            return AudioChunk(
                data=chunk_data,
                sample_rate=self.DEFAULT_SAMPLE_RATE,
                channels=self.DEFAULT_CHANNELS,
                sample_width=self.DEFAULT_SAMPLE_WIDTH,
            )

    def stop_recording(self) -> bytes:
        """Stop synthetic recording and return accumulated bytes."""
        with self._lock:
            self._is_recording = False
            result = bytes(self._collected_bytes)
            self._collected_bytes.clear()
            self._queue.clear()
            logger.info("MockAudioInput stopped; captured %d bytes", len(result))
            return result


class SoundDeviceAudioInput(BaseAudioInput):
    """Microphone driver wrapping the sounddevice library for Windows 11 hardware capture."""

    def __init__(self, max_recording_seconds: float = BaseAudioInput.MAX_RECORDING_SECONDS) -> None:
        super().__init__(max_recording_seconds=max_recording_seconds)
        self._stream: Any = None
        self._queue: deque[bytes] = deque()
        self._collected_bytes = bytearray()

    def _audio_callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        """Internal callback invoked by sounddevice for incoming PCM frames."""
        if status:
            logger.warning("SoundDevice capture status warning: %s", status)
        with self._lock:
            if self.is_recording:
                chunk_bytes = bytes(indata)
                if len(self._collected_bytes) + len(chunk_bytes) <= self.max_buffer_bytes:
                    self._queue.append(chunk_bytes)
                    self._collected_bytes.extend(chunk_bytes)
                else:
                    self._is_recording = False

    def start_recording(self, sample_rate: int = 16000, channels: int = 1) -> None:
        """Initialize and start sounddevice RawInputStream."""
        with self._lock:
            try:
                import sounddevice as sd  # type: ignore[import-untyped]
            except ImportError as err:
                raise AudioInputError(
                    "sounddevice library is not installed or audio hardware is unavailable."
                ) from err

            try:
                self._queue.clear()
                self._collected_bytes.clear()
                self._stream = sd.RawInputStream(
                    samplerate=sample_rate,
                    channels=channels,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._is_recording = True
                self._start_time = time.time()
                logger.info("SoundDevice recording started on hardware microphone.")
            except Exception as exc:
                self._is_recording = False
                raise AudioInputError(f"Failed to open audio input stream: {exc}") from exc

    def read_chunk(self, max_bytes: int | None = None) -> AudioChunk | None:
        """Retrieve the next chunk captured by the hardware stream callback."""
        with self._lock:
            if not self._queue:
                return None
            data = self._queue.popleft()
            return AudioChunk(
                data=data,
                sample_rate=self.DEFAULT_SAMPLE_RATE,
                channels=self.DEFAULT_CHANNELS,
                sample_width=self.DEFAULT_SAMPLE_WIDTH,
            )

    def stop_recording(self) -> bytes:
        """Stop hardware stream and return accumulated bytes."""
        with self._lock:
            self._is_recording = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Error closing SoundDevice stream: %s", exc)
                finally:
                    self._stream = None

            result = bytes(self._collected_bytes)
            self._collected_bytes.clear()
            self._queue.clear()
            logger.info("SoundDevice recording stopped; collected %d bytes", len(result))
            return result
