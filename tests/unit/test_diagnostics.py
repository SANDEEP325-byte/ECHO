"""Unit tests for ECHO Phase 10A: Pre-flight diagnostics and runtime lifecycle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.configuration.diagnostics import (
    ComponentStatus,
    DiagnosticCheck,
    SystemHealth,
    check_brain_core,
    check_configuration,
    check_database,
    check_directories,
    check_ollama_service,
    check_python_runtime,
    check_voice_subsystem,
    run_diagnostics,
    run_diagnostics_sync,
)
from services.configuration.lifecycle import RuntimeLifecycle


@pytest.mark.anyio
async def test_check_python_runtime_valid() -> None:
    """Verify runtime check passes on supported Python versions (>= 3.12)."""
    check = await check_python_runtime()
    assert check.name == "Python Runtime"
    assert check.is_core is True
    assert check.status == ComponentStatus.READY


@pytest.mark.anyio
async def test_check_python_runtime_unsupported() -> None:
    """Verify runtime check blocks when Python version is < 3.12."""
    with patch("sys.version_info", (3, 11, 2, "final", 0)):
        check = await check_python_runtime()
        assert check.status == ComponentStatus.BLOCKED
        assert "Python 3.12+ is required" in check.message


@pytest.mark.anyio
async def test_check_configuration_valid() -> None:
    """Verify configuration check passes when settings are accessible."""
    check = await check_configuration()
    assert check.name == "Configuration"
    assert check.is_core is True
    assert check.status == ComponentStatus.READY
    assert "ECHO" in check.message


@pytest.mark.anyio
async def test_check_configuration_failure() -> None:
    """Verify configuration check marks BLOCKED on config error."""
    with patch(
        "services.configuration.diagnostics.getattr",
        side_effect=RuntimeError("Config error"),
    ):
        check = await check_configuration()
        assert check.status == ComponentStatus.BLOCKED
        assert "Configuration loading failed" in check.message


@pytest.mark.anyio
async def test_check_directories_success(tmp_path: Path) -> None:
    """Verify directory check passes and ensures paths exist."""
    check = await check_directories()
    assert check.name == "Storage Directories"
    assert check.is_core is True
    assert check.status == ComponentStatus.READY


@pytest.mark.anyio
async def test_check_directories_failure() -> None:
    """Verify directory check reports BLOCKED if directory creation fails."""
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")):
        check = await check_directories()
        assert check.status == ComponentStatus.BLOCKED
        assert "Storage directories unwritable" in check.message


@pytest.mark.anyio
async def test_check_database_success() -> None:
    """Verify SQLite database initialization check passes."""
    check = await check_database()
    assert check.name == "SQLite Database"
    assert check.is_core is True
    assert check.status == ComponentStatus.READY


@pytest.mark.anyio
async def test_check_database_failure() -> None:
    """Verify database check marks BLOCKED on connection failure."""
    with patch(
        "services.memory.database.initialize_database",
        side_effect=RuntimeError("DB locked"),
    ):
        check = await check_database()
        assert check.status == ComponentStatus.BLOCKED
        assert "Database initialization failed" in check.message


@pytest.mark.anyio
async def test_check_brain_core_success() -> None:
    """Verify Brain core instantiation check passes."""
    check = await check_brain_core()
    assert check.name == "Cognitive Brain"
    assert check.is_core is True
    assert check.status == ComponentStatus.READY


@pytest.mark.anyio
async def test_check_brain_core_failure() -> None:
    """Verify Brain core failure marks BLOCKED."""
    with patch("services.brain.brain.echo_brain", None):
        check = await check_brain_core()
        assert check.status == ComponentStatus.BLOCKED
        assert "uninitialized" in check.message


@pytest.mark.anyio
async def test_check_ollama_available() -> None:
    """Verify Ollama check reports READY when local daemon is responsive."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with (
        patch("services.configuration.diagnostics.settings.ai_provider", "ollama"),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        check = await check_ollama_service()
        assert check.name == "Ollama LLM Service"
        assert check.is_core is False
        assert check.status == ComponentStatus.READY
        assert "Ollama reachable" in check.message


@pytest.mark.anyio
async def test_check_ollama_unavailable() -> None:
    """Verify Ollama check marks DEGRADED (never BLOCKED) when unreachable."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection refused")
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with (
        patch("services.configuration.diagnostics.settings.ai_provider", "ollama"),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        check = await check_ollama_service()
        assert check.name == "Ollama LLM Service"
        assert check.is_core is False
        assert check.status == ComponentStatus.DEGRADED
        assert "Ollama offline" in check.message


@pytest.mark.anyio
async def test_check_voice_available() -> None:
    """Verify voice check returns READY when hardware is detected."""
    mock_sd = MagicMock()
    mock_sd.query_devices.return_value = [{"name": "Default Mic"}]

    with patch.dict("sys.modules", {"sounddevice": mock_sd}):
        check = await check_voice_subsystem()
        assert check.name == "Voice Subsystem"
        assert check.is_core is False
        assert check.status == ComponentStatus.READY


@pytest.mark.anyio
async def test_check_voice_unavailable() -> None:
    """Verify voice check marks DEGRADED (never BLOCKED) when voice hardware is absent."""
    with patch.dict("sys.modules", {"sounddevice": None}):
        check = await check_voice_subsystem()
        assert check.name == "Voice Subsystem"
        assert check.is_core is False
        assert check.status == ComponentStatus.DEGRADED
        assert "Audio hardware not configured" in check.message


@pytest.mark.anyio
async def test_run_diagnostics_all_healthy() -> None:
    """Verify run_diagnostics produces overall READY status when all checks pass."""
    with (
        patch(
            "services.configuration.diagnostics.check_python_runtime",
            return_value=DiagnosticCheck("Python", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_configuration",
            return_value=DiagnosticCheck("Config", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_directories",
            return_value=DiagnosticCheck("Dirs", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_database",
            return_value=DiagnosticCheck("DB", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_brain_core",
            return_value=DiagnosticCheck("Brain", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_ollama_service",
            return_value=DiagnosticCheck("Ollama", ComponentStatus.READY, "OK", False),
        ),
        patch(
            "services.configuration.diagnostics.check_voice_subsystem",
            return_value=DiagnosticCheck("Voice", ComponentStatus.READY, "OK", False),
        ),
    ):
        health: SystemHealth = await run_diagnostics()
        assert health.overall_status == ComponentStatus.READY
        assert health.is_runnable is True
        assert len(health.checks) == 7


@pytest.mark.anyio
async def test_run_diagnostics_degraded_when_optional_fails() -> None:
    """Verify system remains runnable and reports DEGRADED if optional services are down."""
    with (
        patch(
            "services.configuration.diagnostics.check_python_runtime",
            return_value=DiagnosticCheck("Python", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_configuration",
            return_value=DiagnosticCheck("Config", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_directories",
            return_value=DiagnosticCheck("Dirs", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_database",
            return_value=DiagnosticCheck("DB", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_brain_core",
            return_value=DiagnosticCheck("Brain", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_ollama_service",
            return_value=DiagnosticCheck("Ollama", ComponentStatus.DEGRADED, "Offline", False),
        ),
        patch(
            "services.configuration.diagnostics.check_voice_subsystem",
            return_value=DiagnosticCheck("Voice", ComponentStatus.DEGRADED, "No mic", False),
        ),
    ):
        health: SystemHealth = await run_diagnostics()
        assert health.overall_status == ComponentStatus.DEGRADED
        assert health.is_runnable is True


@pytest.mark.anyio
async def test_run_diagnostics_blocked_when_core_fails() -> None:
    """Verify system is marked BLOCKED and not runnable if any core check fails."""
    with (
        patch(
            "services.configuration.diagnostics.check_python_runtime",
            return_value=DiagnosticCheck("Python", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_configuration",
            return_value=DiagnosticCheck("Config", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_directories",
            return_value=DiagnosticCheck("Dirs", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_database",
            return_value=DiagnosticCheck("DB", ComponentStatus.BLOCKED, "Corrupt", True),
        ),
        patch(
            "services.configuration.diagnostics.check_brain_core",
            return_value=DiagnosticCheck("Brain", ComponentStatus.READY, "OK", True),
        ),
        patch(
            "services.configuration.diagnostics.check_ollama_service",
            return_value=DiagnosticCheck("Ollama", ComponentStatus.READY, "OK", False),
        ),
        patch(
            "services.configuration.diagnostics.check_voice_subsystem",
            return_value=DiagnosticCheck("Voice", ComponentStatus.READY, "OK", False),
        ),
    ):
        health: SystemHealth = await run_diagnostics()
        assert health.overall_status == ComponentStatus.BLOCKED
        assert health.is_runnable is False


def test_run_diagnostics_sync() -> None:
    """Verify synchronous diagnostic runner functions properly."""
    health = run_diagnostics_sync()
    assert isinstance(health, SystemHealth)
    assert len(health.checks) >= 5


def test_safe_diagnostic_output_no_secrets() -> None:
    """Verify diagnostics output never leaks API keys, passwords, or tokens."""
    health = run_diagnostics_sync()
    for check in health.checks:
        lower_msg = check.message.lower()
        assert "api_key" not in lower_msg
        assert "secret" not in lower_msg
        assert "password" not in lower_msg
        assert "token" not in lower_msg


# ---------------------------------------------------------------------------
# Lifecycle Manager Tests
# ---------------------------------------------------------------------------


def test_lifecycle_shutdown_idempotent() -> None:
    """Verify shutdown can be called multiple times without duplicate executions."""
    lifecycle = RuntimeLifecycle()
    cleanup_mock = MagicMock()
    lifecycle.register_cleanup(cleanup_mock)

    assert not lifecycle.is_shutting_down
    lifecycle.shutdown_sync()
    assert lifecycle.is_shutting_down
    assert cleanup_mock.call_count == 1

    # Second shutdown call must be a no-op
    lifecycle.shutdown_sync()
    assert cleanup_mock.call_count == 1


@pytest.mark.anyio
async def test_lifecycle_async_shutdown() -> None:
    """Verify async shutdown executes registered sync and async cleanup hooks."""
    lifecycle = RuntimeLifecycle()
    sync_mock = MagicMock()
    async_mock = AsyncMock()

    lifecycle.register_cleanup(sync_mock)
    lifecycle.register_cleanup(async_mock)

    await lifecycle.shutdown()
    assert lifecycle.is_shutting_down
    sync_mock.assert_called_once()
    async_mock.assert_awaited_once()


def test_lifecycle_cleanup_error_resilience() -> None:
    """Verify that an exception in one cleanup hook does not prevent others from running."""
    lifecycle = RuntimeLifecycle()
    failing_mock = MagicMock(side_effect=RuntimeError("Cleanup crash"))
    healthy_mock = MagicMock()

    lifecycle.register_cleanup(failing_mock)
    lifecycle.register_cleanup(healthy_mock)

    # Should not raise
    lifecycle.shutdown_sync()
    failing_mock.assert_called_once()
    healthy_mock.assert_called_once()
