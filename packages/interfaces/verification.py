from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    result: Any = None
    error: str | None = None