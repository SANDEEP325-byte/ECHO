"""Wake Detection Mechanisms and Local Triggers (Phase 6D).

Provides replaceable wake detection abstractions for Project ECHO.
Enforces local-first, privacy-preserving operation without automatic runtime downloads,
hidden background processes, or audio persistence.
Wake detection events only transition the session into LISTENING; they NEVER execute tools.
"""

import math
import struct
from abc import ABC
from pathlib import Path
from typing import Any

from packages.interfaces.voice import WakeDetector
from services.logging.logger import logger  # type: ignore[attr-defined]
from services.voice.errors import ModelUnavailableError, WakeDetectionError


class BaseWakeDetector(WakeDetector, ABC):
    """Base class for wake detection mechanisms."""


class MockWakeDetector(BaseWakeDetector):
    """Deterministic, 100% offline mock wake detector for testing."""

    def __init__(
        self,
        detection_pattern: list[bool] | None = None,
        is_available: bool = True,
        simulate_error: str | None = None,
    ) -> None:
        self.detection_pattern = list(detection_pattern) if detection_pattern is not None else []
        self.is_available_flag = is_available
        self.simulate_error = simulate_error
        self.call_count = 0

    def is_available(self) -> bool:
        """Return configured availability status."""
        return self.is_available_flag

    def detect(self, chunk: bytes, sample_rate: int = 16000) -> bool:
        """Return deterministic wake indication based on configured pattern."""
        if not self.is_available():
            raise ModelUnavailableError(
                "Mock wake detector is not available locally. Runtime downloads are prohibited."
            )

        if self.simulate_error:
            raise WakeDetectionError(f"Mock wake detection error: {self.simulate_error}")

        if self.call_count < len(self.detection_pattern):
            result = self.detection_pattern[self.call_count]
        else:
            result = False

        self.call_count += 1
        if result:
            logger.info(
                "MockWakeDetector detected synthetic wake event on chunk #%d", self.call_count
            )
        return result

    def reset(self) -> None:
        """Reset internal call counter."""
        self.call_count = 0


class LocalEnergyWakeDetector(BaseWakeDetector):
    """Energy/activity-based local audio trigger (NOT a true wake-word recognizer).

    Detects prominent acoustic energy bursts to initiate a voice session in ₹0,
    zero-dependency environments. This is strictly a threshold-based activity trigger,
    not a semantic or phonetic wake-word model.
    """

    def __init__(self, energy_threshold: float = 1500.0) -> None:
        self.energy_threshold = energy_threshold

    @staticmethod
    def _calculate_rms(chunk: bytes) -> float:
        """Calculate RMS energy of 16-bit signed mono PCM chunk."""
        if not chunk or len(chunk) < 2:
            return 0.0
        num_samples = len(chunk) // 2
        fmt = f"<{num_samples}h"
        try:
            samples = struct.unpack(fmt, chunk[: num_samples * 2])
        except struct.error:
            return 0.0
        sum_sq = sum(s * s for s in samples)
        return math.sqrt(sum_sq / num_samples)

    def is_available(self) -> bool:
        """Always available as a pure Python fallback."""
        return True

    def detect(self, chunk: bytes, sample_rate: int = 16000) -> bool:
        """Return True if chunk RMS energy exceeds the burst threshold."""
        rms = self._calculate_rms(chunk)
        if rms >= self.energy_threshold:
            logger.info(
                "LocalEnergyWakeDetector triggered on acoustic energy burst (RMS=%.1f)", rms
            )
            return True
        return False

    def reset(self) -> None:
        """No internal state to reset."""


class OpenWakeWordDetector(BaseWakeDetector):
    """Pluggable adapter for openWakeWord neural wake-word detection.

    Requirements:
    - Never triggers network downloads at runtime.
    - If local model files are absent, raises ModelUnavailableError.
    - Operates purely in-memory; raw audio is never written to disk.
    - Wake detection transitions the voice session into LISTENING; it never executes tools.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        model_name: str = "hey_echo",
        inference_framework: str = "onnx",
    ) -> None:
        self.model_name = model_name
        self.inference_framework = inference_framework
        self.model_path = (
            Path(model_path) if model_path else Path("models") / "wakeword" / f"{model_name}.onnx"
        )
        self._model: Any = None

    def is_available(self) -> bool:
        """Check whether local wake-word model files exist without making network calls."""
        if not self.model_path.exists() or not self.model_path.is_file():
            return False

        try:
            import openwakeword  # type: ignore[import-not-found]  # noqa: F401

            return True
        except ImportError:
            return False

    def detect(self, chunk: bytes, sample_rate: int = 16000) -> bool:
        """Run local neural inference on the PCM chunk for wake-word detection."""
        if not self.is_available():
            raise ModelUnavailableError(
                f"Wake-word model '{self.model_name}' was not found at '{self.model_path}' or "
                "openwakeword is not installed. Automatic runtime downloads are prohibited."
            )

        if not chunk:
            return False

        try:
            if self._model is None:
                from openwakeword.model import Model  # type: ignore[import-not-found]

                self._model = Model(
                    wakeword_models=[str(self.model_path)],
                    inference_framework=self.inference_framework,
                )

            import numpy as np

            audio_data = np.frombuffer(chunk, dtype=np.int16)
            self._model.predict(audio_data)

            for mdl in self._model.prediction_buffer:
                scores = list(self._model.prediction_buffer[mdl])
                if scores and scores[-1] > 0.5:
                    logger.info("OpenWakeWordDetector: wake word detected (score=%.2f)", scores[-1])
                    return True

            return False
        except Exception as exc:
            raise WakeDetectionError(f"OpenWakeWord inference failed: {exc}") from exc

    def reset(self) -> None:
        """Reset internal prediction buffers."""
        if self._model is not None and hasattr(self._model, "reset"):
            self._model.reset()
