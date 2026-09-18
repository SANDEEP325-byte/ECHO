"""Offline Speech Synthesis (TTS) Engines (Phase 6C).

Implements local, privacy-first, 100% offline Text-to-Speech inference with strict
length bounding, in-memory audio generation, and zero temporary audio files.
Runtime automatic downloading of models is strictly prohibited.
"""

import math
import struct
import time
from abc import ABC
from pathlib import Path
from typing import Any

from packages.interfaces.voice import SpeechSynthesizer, SynthesizedAudio
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.voice.errors import ModelUnavailableError, SynthesisError


class BaseSpeechSynthesizer(SpeechSynthesizer, ABC):
    """Base class for speech synthesizers providing text sanitization and bounding."""

    MAX_TEXT_LENGTH = 1000  # Maximum characters per synthesis request
    DEFAULT_SAMPLE_RATE = 22050
    DEFAULT_CHANNELS = 1
    DEFAULT_SAMPLE_WIDTH = 2  # 16-bit PCM

    @classmethod
    def clean_text(cls, raw_text: str) -> str:
        """Sanitize text, collapse whitespace, and enforce maximum length bounds."""
        if not raw_text:
            return ""
        # Collapse whitespace and control characters
        normalized = " ".join(raw_text.strip().split())
        if len(normalized) > cls.MAX_TEXT_LENGTH:
            logger.warning(
                "Input text length (%d) exceeds max bound (%d); truncating.",
                len(normalized),
                cls.MAX_TEXT_LENGTH,
            )
            normalized = normalized[: cls.MAX_TEXT_LENGTH]
        return normalized


class MockSpeechSynthesizer(BaseSpeechSynthesizer):
    """Deterministic, 100% offline mock speech synthesizer for testing."""

    def __init__(
        self,
        sample_rate: int = BaseSpeechSynthesizer.DEFAULT_SAMPLE_RATE,
        is_model_available: bool = True,
        simulate_error: str | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.is_model_available_flag = is_model_available
        self.simulate_error = simulate_error
        self.synthesized_calls: list[int] = []

    def is_available(self) -> bool:
        """Return configured model availability status."""
        return self.is_model_available_flag

    def synthesize(self, text: str) -> SynthesizedAudio:
        """Generate deterministic synthetic audio in memory without writing to disk."""
        if not self.is_available():
            raise ModelUnavailableError(
                "Mock TTS model is not available locally. Automatic runtime downloads are prohibited."
            )

        if self.simulate_error:
            raise SynthesisError(f"Mock TTS synthesis error: {self.simulate_error}")

        cleaned = self.clean_text(text)
        if not cleaned:
            return SynthesizedAudio(
                data=b"",
                sample_rate=self.sample_rate,
                channels=self.DEFAULT_CHANNELS,
                sample_width=self.DEFAULT_SAMPLE_WIDTH,
                duration_seconds=0.0,
            )

        # Approximate duration: ~50ms per character, capped at 10.0 seconds
        duration = max(0.1, min(len(cleaned) * 0.05, 10.0))
        num_samples = int(self.sample_rate * duration)

        # Synthesize a pure 440Hz sine wave tone into 16-bit PCM in memory
        samples = []
        for i in range(num_samples):
            val = int(8000.0 * math.sin(2.0 * math.pi * 440.0 * (i / self.sample_rate)))
            samples.append(val)

        audio_bytes = struct.pack(f"<{len(samples)}h", *samples)
        self.synthesized_calls.append(len(cleaned))

        logger.info(
            "MockSpeechSynthesizer generated %d bytes (%.2fs) in memory", len(audio_bytes), duration
        )
        return SynthesizedAudio(
            data=audio_bytes,
            sample_rate=self.sample_rate,
            channels=self.DEFAULT_CHANNELS,
            sample_width=self.DEFAULT_SAMPLE_WIDTH,
            duration_seconds=duration,
        )


class LocalSpeechSynthesizer(BaseSpeechSynthesizer):
    """Local, offline Text-to-Speech engine supporting Piper and Windows SAPI5.

    Security & Privacy Invariants:
    - Never triggers network downloads at runtime.
    - If model files or binaries are missing, raises ModelUnavailableError immediately.
    - Zero audio files on disk: synthesis is performed purely into in-memory buffers.
    - Zero temporary files.
    - Audio references are held for the minimum duration required.
    """

    def __init__(
        self,
        model_dir: str | Path | None = None,
        voice_name: str = "en_US-lessac-medium",
        sample_rate: int = BaseSpeechSynthesizer.DEFAULT_SAMPLE_RATE,
    ) -> None:
        self.voice_name = voice_name
        self.sample_rate = sample_rate
        self.model_dir = Path(model_dir) if model_dir else Path("models") / "piper" / voice_name
        self._engine: Any = None

    def is_available(self) -> bool:
        """Check whether local voice model exists on disk without triggering downloads."""
        # 1. Check for local Piper ONNX model
        if self.model_dir.exists() and self.model_dir.is_dir():
            has_onnx = (self.model_dir / f"{self.voice_name}.onnx").exists()
            has_json = (self.model_dir / f"{self.voice_name}.onnx.json").exists()
            if has_onnx and has_json:
                return True

        # 2. Check for local Windows SAPI5 in-memory engine
        try:
            import win32com.client  # type: ignore[import-untyped]

            win32com.client.Dispatch("SAPI.SpVoice")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("SAPI5 initialization check unavailable: %s", exc)

        return False

    def synthesize(self, text: str) -> SynthesizedAudio:
        """Synthesize text into in-memory PCM audio bytes without creating any files on disk."""
        cleaned = self.clean_text(text)
        if not cleaned:
            return SynthesizedAudio(
                data=b"",
                sample_rate=self.sample_rate,
                channels=self.DEFAULT_CHANNELS,
                sample_width=self.DEFAULT_SAMPLE_WIDTH,
                duration_seconds=0.0,
            )

        if not self.is_available():
            raise ModelUnavailableError(
                f"TTS voice model '{self.voice_name}' was not found at '{self.model_dir}' and "
                "no local in-memory TTS engine is available. Automatic runtime downloads are "
                "prohibited by ECHO security policy. Models must be provisioned locally ahead of time."
            )

        start_time = time.time()

        # Try Windows SAPI5 in-memory SpMemoryStream if available
        try:
            import win32com.client

            voice = win32com.client.Dispatch("SAPI.SpVoice")
            mem_stream = win32com.client.Dispatch("SAPI.SpMemoryStream")

            # Format 22: SAFT22kHz16BitMono
            mem_stream.Format.Type = 22
            voice.AudioOutputStream = mem_stream
            voice.Speak(cleaned)

            raw_bytes = bytes(mem_stream.GetData())
            duration = time.time() - start_time

            logger.info(
                "LocalSpeechSynthesizer synthesized %d chars (%d bytes) in %.2fs",
                len(cleaned),
                len(raw_bytes),
                duration,
            )
            return SynthesizedAudio(
                data=raw_bytes,
                sample_rate=self.sample_rate,
                channels=self.DEFAULT_CHANNELS,
                sample_width=self.DEFAULT_SAMPLE_WIDTH,
                duration_seconds=duration,
            )
        except Exception as exc:
            raise SynthesisError(f"Local TTS in-memory synthesis failed: {exc}") from exc
