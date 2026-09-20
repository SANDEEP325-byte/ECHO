"""Pre-Flight System Diagnostics (Phase 10A).

Evaluates the local environment and subsystems before startup.
Distinguishes between:
- READY: Operational component.
- DEGRADED: Optional component unavailable (e.g. Ollama offline, microphone absent),
  allowing ECHO to run in deterministic fallback mode.
- BLOCKED: Core prerequisite failed (e.g. incompatible Python, unwritable database),
  preventing safe execution.

Guarantees:
- Zero external network dependencies.
- Zero secrets or sensitive filesystem paths leaked in outputs.
- Fast execution with strict localhost timeouts (<= 1.5s).
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from services.configuration.settings import settings
from services.logging.logger import logger  # type: ignore[attr-defined]


class ComponentStatus(str, Enum):
    """Readiness status of a system component."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass
class DiagnosticCheck:
    """Individual diagnostic inspection result."""

    name: str
    status: ComponentStatus
    message: str
    is_core: bool = True
    details: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "is_core": self.is_core,
            "details": self.details,
        }


@dataclass
class SystemHealth:
    """Overall system health evaluation."""

    overall_status: ComponentStatus
    checks: list[DiagnosticCheck] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def is_runnable(self) -> bool:
        """Return True if system can safely start (READY or DEGRADED, not BLOCKED)."""
        return self.overall_status != ComponentStatus.BLOCKED

    def get_check(self, name: str) -> DiagnosticCheck | None:
        """Lookup check by name."""
        for c in self.checks:
            if c.name.lower() == name.lower():
                return c
        return None


async def check_python_runtime() -> DiagnosticCheck:
    """Verify Python interpreter version is 3.12+."""
    major, minor, micro = sys.version_info[:3]
    if (major, minor) < (3, 12):
        return DiagnosticCheck(
            name="Python Runtime",
            status=ComponentStatus.BLOCKED,
            message=f"Python 3.12+ is required (detected Python {major}.{minor}.{micro}).",
            is_core=True,
        )
    return DiagnosticCheck(
        name="Python Runtime",
        status=ComponentStatus.READY,
        message=f"Python {major}.{minor}.{micro} compatible.",
        is_core=True,
    )


async def check_configuration() -> DiagnosticCheck:
    """Verify application configuration loads without exposing credentials."""
    try:
        env_name = getattr(settings, "app_env", "development")
        app_name = getattr(settings, "app_name", "ECHO")
        version = getattr(settings, "app_version", "0.1.0")
        provider = getattr(settings, "ai_provider", "ollama")
        return DiagnosticCheck(
            name="Configuration",
            status=ComponentStatus.READY,
            message=f"{app_name} v{version} configuration loaded (env={env_name}, provider={provider}).",
            is_core=True,
        )
    except Exception as exc:  # noqa: BLE001
        return DiagnosticCheck(
            name="Configuration",
            status=ComponentStatus.BLOCKED,
            message=f"Configuration loading failed: {exc}",
            is_core=True,
        )


async def check_directories() -> DiagnosticCheck:
    """Verify required local data and log storage directories are writable."""
    dirs_to_check = [Path("data"), Path("logs")]
    unwritable: list[str] = []

    for d in dirs_to_check:
        try:
            d.mkdir(parents=True, exist_ok=True)
            test_file = d / ".healthcheck_write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            unwritable.append(d.name)

    if unwritable:
        return DiagnosticCheck(
            name="Storage Directories",
            status=ComponentStatus.BLOCKED,
            message=f"Storage directories unwritable: {', '.join(unwritable)}.",
            is_core=True,
        )

    return DiagnosticCheck(
        name="Storage Directories",
        status=ComponentStatus.READY,
        message="Local data and logs storage verified.",
        is_core=True,
    )


async def check_database() -> DiagnosticCheck:
    """Verify SQLite memory database initialization."""
    try:
        from services.memory.database import initialize_database

        initialize_database()
        return DiagnosticCheck(
            name="SQLite Database",
            status=ComponentStatus.READY,
            message="SQLite memory database operational.",
            is_core=True,
        )
    except Exception as exc:  # noqa: BLE001
        return DiagnosticCheck(
            name="SQLite Database",
            status=ComponentStatus.BLOCKED,
            message=f"Database initialization failed: {exc}",
            is_core=True,
        )


async def check_brain_core() -> DiagnosticCheck:
    """Verify ECHOBrain cognitive engine and memory manager initialization."""
    try:
        from services.brain.brain import echo_brain

        if echo_brain is None:
            return DiagnosticCheck(
                name="Cognitive Brain",
                status=ComponentStatus.BLOCKED,
                message="ECHOBrain singleton is uninitialized.",
                is_core=True,
            )
        return DiagnosticCheck(
            name="Cognitive Brain",
            status=ComponentStatus.READY,
            message="ECHOBrain cognitive pipeline operational.",
            is_core=True,
        )
    except Exception as exc:  # noqa: BLE001
        return DiagnosticCheck(
            name="Cognitive Brain",
            status=ComponentStatus.BLOCKED,
            message=f"ECHOBrain initialization failed: {exc}",
            is_core=True,
        )


async def check_ollama_service() -> DiagnosticCheck:
    """Optionally verify local Ollama daemon connectivity on localhost."""
    ai_provider = getattr(settings, "ai_provider", "ollama")
    if ai_provider != "ollama":
        return DiagnosticCheck(
            name="Ollama LLM Service",
            status=ComponentStatus.READY,
            message=f"Using alternative provider '{ai_provider}'.",
            is_core=False,
        )

    ollama_host = getattr(settings, "ollama_host", "http://localhost:11434")
    model_name = getattr(settings, "ollama_model", "qwen3:0.6b")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{ollama_host}/api/version")
            if resp.status_code == 200:
                return DiagnosticCheck(
                    name="Ollama LLM Service",
                    status=ComponentStatus.READY,
                    message=f"Ollama reachable on localhost (model: {model_name}).",
                    is_core=False,
                )
    except Exception:  # noqa: BLE001, S110
        pass

    return DiagnosticCheck(
        name="Ollama LLM Service",
        status=ComponentStatus.DEGRADED,
        message="Ollama offline on localhost:11434 (deterministic tools & canned fallback active).",
        is_core=False,
    )


async def check_voice_subsystem() -> DiagnosticCheck:
    """Optionally inspect audio hardware and voice driver availability."""
    try:
        import sounddevice as sd  # type: ignore[import-untyped]

        devices = sd.query_devices()
        if devices:
            return DiagnosticCheck(
                name="Voice Subsystem",
                status=ComponentStatus.READY,
                message="Audio hardware drivers detected.",
                is_core=False,
            )
    except Exception:  # noqa: BLE001, S110
        pass

    return DiagnosticCheck(
        name="Voice Subsystem",
        status=ComponentStatus.DEGRADED,
        message="Audio hardware not configured (text CLI mode fully operational).",
        is_core=False,
    )


async def run_diagnostics() -> SystemHealth:
    """Execute all pre-flight diagnostic checks and produce SystemHealth."""
    logger.info("Executing pre-flight diagnostics...")

    # Run all checks concurrently
    checks = await asyncio.gather(
        check_python_runtime(),
        check_configuration(),
        check_directories(),
        check_database(),
        check_brain_core(),
        check_ollama_service(),
        check_voice_subsystem(),
    )

    has_blocked = any(c.status == ComponentStatus.BLOCKED for c in checks if c.is_core)
    has_degraded = any(c.status == ComponentStatus.DEGRADED for c in checks)

    if has_blocked:
        overall = ComponentStatus.BLOCKED
    elif has_degraded:
        overall = ComponentStatus.DEGRADED
    else:
        overall = ComponentStatus.READY

    logger.info("Diagnostics completed: overall_status={}", overall.value)
    return SystemHealth(overall_status=overall, checks=list(checks))


def run_diagnostics_sync() -> SystemHealth:
    """Synchronously run pre-flight diagnostics."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In an already running event loop, create task or run in runner
            return asyncio.run(run_diagnostics())
        return loop.run_until_complete(run_diagnostics())
    except RuntimeError:
        return asyncio.run(run_diagnostics())
