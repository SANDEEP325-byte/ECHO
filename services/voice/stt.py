"""Offline Speech-to-Text (STT) Engines (Phase 6B).

Implements local, privacy-first, 100% offline Speech-to-Text inference using
Faster-Whisper (CTranslate2) and deterministic mock recognizers.
Runtime automatic downloading of models is strictly prohibited.
"""

import time
from abc import ABC
from pathlib import Path
from typing import Any

from packages.interfaces.voice import RecognitionResult, SpeechRecognizer
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.voice.errors import ModelUnavailableError, RecognitionError


class BaseSpeechRecognizer(SpeechRecognizer, ABC):
    """Base class for STT engines with common validation and text normalization."""

    @staticmethod
    def normalize_text(raw_text: str) -> str:
        """Strip control characters, leading/trailing whitespace, and normalize transcript."""
        if not raw_text:
            return ""
        # Collapse multiple spaces and trim
        return " ".join(raw_text.strip().split())


class MockSpeechRecognizer(BaseSpeechRecognizer):
    """Deterministic, 100% offline mock STT recognizer for unit and integration testing."""

    def __init__(
        self,
        default_transcript: str = "open terminal",
        confidence: float = 0.95,
        language: str = "en",
        simulate_error: str | None = None,
        is_model_available: bool = True,
    ) -> None:
        self.default_transcript = default_transcript
        self.confidence = confidence
        self.language = language
        self.simulate_error = simulate_error
        self.is_model_available_flag = is_model_available
        self.transcribed_calls: list[int] = []

    def is_available(self) -> bool:
        """Return configured availability status."""
        return self.is_model_available_flag

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> RecognitionResult:
        """Return deterministic mock recognition result."""
        if not self.is_available():
            raise ModelUnavailableError(
                "Mock STT model is not available locally. Runtime downloads are prohibited."
            )

        if self.simulate_error:
            raise RecognitionError(f"Mock STT inference error: {self.simulate_error}")

        self.transcribed_calls.append(len(audio_bytes))

        # Calculate approximate duration based on 16kHz mono 16-bit PCM
        bytes_per_second = sample_rate * 2
        duration = len(audio_bytes) / bytes_per_second if bytes_per_second > 0 else 0.0

        clean_text = self.normalize_text(self.default_transcript)
        return RecognitionResult(
            text=clean_text,
            confidence=self.confidence,
            language=self.language,
            duration_seconds=duration,
            is_empty=(len(clean_text) == 0),
        )


class FasterWhisperRecognizer(BaseSpeechRecognizer):
    """Local, offline Speech-to-Text inference powered by Faster-Whisper / CTranslate2.

    Security & Privacy Rules:
    - Never triggers network downloads at runtime.
    - If model files are absent from local storage, raises ModelUnavailableError immediately.
    - Operates strictly on in-memory buffers; raw audio is never persisted to disk.
    """

    DEFAULT_MODEL_NAME = "base.en"

    def __init__(
        self,
        model_dir: str | Path | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_dir = Path(model_dir) if model_dir else Path("models") / f"whisper-{model_name}"
        self._model: Any = None

    def is_available(self) -> bool:
        """Check whether local model weights exist on disk without triggering downloads."""
        if not self.model_dir.exists() or not self.model_dir.is_dir():
            return False

        # Verify key model files exist locally
        has_model_bin = (self.model_dir / "model.bin").exists()
        has_config = (self.model_dir / "config.json").exists()
        return has_model_bin and has_config

    def _load_model(self) -> Any:
        """Load the local CTranslate2 Whisper model into memory if available."""
        if self._model is not None:
            return self._model

        if not self.is_available():
            raise ModelUnavailableError(
                f"STT model '{self.model_name}' was not found at local directory '{self.model_dir}'. "
                "Automatic runtime downloading is prohibited by ECHO security policy. "
                "The model must be provisioned locally ahead of time."
            )

        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        except ImportError as err:
            raise ModelUnavailableError(
                "faster-whisper library is not installed in the active environment."
            ) from err

        try:
            logger.info(
                "Loading local offline Faster-Whisper model from '%s' (device=%s, compute=%s)...",
                self.model_dir,
                self.device,
                self.compute_type,
            )
            self._model = WhisperModel(
                str(self.model_dir),
                device=self.device,
                compute_type=self.compute_type,
                local_files_only=True,  # Disables HuggingFace network requests
            )
            return self._model
        except Exception as exc:
            raise RecognitionError(f"Failed to initialize Faster-Whisper model: {exc}") from exc

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> RecognitionResult:
        """Transcribe 16kHz mono 16-bit PCM audio bytes using local Whisper model."""
        if not audio_bytes:
            return RecognitionResult(text="", duration_seconds=0.0, is_empty=True)

        model = self._load_model()

        # Convert 16-bit signed PCM to normalized float32 array
        import numpy as np

        start_time = time.time()
        try:
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            segments, info = model.transcribe(
                audio_array,
                beam_size=1,
                language="en",
                vad_filter=False,  # ECHO manages VAD explicitly
            )

            texts = [seg.text for seg in segments]
            full_text = self.normalize_text(" ".join(texts))

            duration = time.time() - start_time
            confidence = info.avg_logprob if hasattr(info, "avg_logprob") else 0.9

            logger.info(
                "Transcribed audio (%d bytes) in %.2fs: '%s'", len(audio_bytes), duration, full_text
            )
            return RecognitionResult(
                text=full_text,
                confidence=confidence,
                language=info.language if hasattr(info, "language") else "en",
                duration_seconds=duration,
                is_empty=(len(full_text) == 0),
            )
        except Exception as exc:
            raise RecognitionError(f"Speech-to-Text inference failed: {exc}") from exc
