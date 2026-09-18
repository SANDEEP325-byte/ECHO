"""Unit tests for ECHO BrowserService (Phase 5B).

Tests process lifecycle, isolation, resource limits, error handling,
idle session cleanup, and security configuration.
100% offline, deterministic, and isolated using mock Playwright factories.
"""

import asyncio
from typing import Any

import pytest

from services.browser.errors import (
    BrowserBinaryMissingError,
    BrowserConfigurationError,
    BrowserLifecycleError,
    BrowserSessionCreationError,
    BrowserSessionLimitError,
    BrowserStartupError,
)
from services.browser.service import BrowserService, BrowserServiceState

# ==============================================================================
# Mock Playwright Hierarchy for Offline Unit Testing
# ==============================================================================


class MockPage:
    """Mock Playwright Page."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class MockBrowserContext:
    """Mock Playwright BrowserContext."""

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.closed = False
        self.default_timeout = 30000
        self.pages: list[MockPage] = []
        self.fail_new_page = False

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    async def new_page(self) -> MockPage:
        if self.fail_new_page:
            raise RuntimeError("Simulated page creation failure")
        page = MockPage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True
        for p in self.pages:
            await p.close()


class MockBrowser:
    """Mock Playwright Browser."""

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.closed = False
        self.contexts: list[MockBrowserContext] = []
        self.fail_new_context = False

    async def new_context(self, **options: Any) -> MockBrowserContext:
        if self.fail_new_context:
            raise RuntimeError("Simulated context creation failure")
        ctx = MockBrowserContext(**options)
        self.contexts.append(ctx)
        return ctx

    async def close(self) -> None:
        self.closed = True
        for c in self.contexts:
            await c.close()


class MockChromium:
    """Mock Playwright Chromium BrowserType."""

    def __init__(self) -> None:
        self.launch_count = 0
        self.last_launch_options: dict[str, Any] = {}
        self.should_fail = False
        self.fail_error: Exception | None = None
        self.last_browser: MockBrowser | None = None

    async def launch(self, **options: Any) -> MockBrowser:
        if self.should_fail and self.fail_error is not None:
            raise self.fail_error
        self.launch_count += 1
        self.last_launch_options = options
        browser = MockBrowser(**options)
        self.last_browser = browser
        return browser


class MockPlaywright:
    """Mock Playwright root instance."""

    def __init__(self) -> None:
        self.chromium = MockChromium()
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def create_mock_playwright_factory() -> tuple[MockPlaywright, Any]:
    """Create a mock playwright instance and factory callable."""
    instance = MockPlaywright()

    def factory() -> MockPlaywright:
        return instance

    return instance, factory


# ==============================================================================
# 1. Configuration Validation
# ==============================================================================


def test_valid_configuration() -> None:
    service = BrowserService(
        headless=True,
        startup_timeout_ms=15000,
        default_timeout_ms=20000,
        max_sessions=4,
        idle_timeout_seconds=120.0,
    )
    assert service.headless is True
    assert service.startup_timeout_ms == 15000
    assert service.default_timeout_ms == 20000
    assert service.max_sessions == 4
    assert service.idle_timeout_seconds == 120.0
    assert service.state == BrowserServiceState.NOT_STARTED


@pytest.mark.parametrize(
    "kwargs,err_substr",
    [
        ({"startup_timeout_ms": 100}, "startup_timeout_ms"),
        ({"startup_timeout_ms": 200000}, "startup_timeout_ms"),
        ({"default_timeout_ms": 500}, "default_timeout_ms"),
        ({"default_timeout_ms": 150000}, "default_timeout_ms"),
        ({"max_sessions": 0}, "max_sessions"),
        ({"max_sessions": 50}, "max_sessions"),
        ({"idle_timeout_seconds": 1.0}, "idle_timeout_seconds"),
        ({"idle_timeout_seconds": 100000.0}, "idle_timeout_seconds"),
    ],
)
def test_invalid_configuration_fails(kwargs: dict[str, Any], err_substr: str) -> None:
    with pytest.raises(BrowserConfigurationError) as exc_info:
        BrowserService(**kwargs)
    assert err_substr in str(exc_info.value)


# ==============================================================================
# 2. Lifecycle: Startup, Shutdown, and Idempotency
# ==============================================================================


@pytest.mark.anyio
async def test_service_startup_and_idempotency() -> None:
    mock_pw, factory = create_mock_playwright_factory()
    service = BrowserService(playwright_launcher=factory)

    assert service.state == BrowserServiceState.NOT_STARTED
    assert service.is_running is False

    await service.start()
    assert service.state == BrowserServiceState.RUNNING
    assert service.is_running is True
    assert mock_pw.chromium.launch_count == 1

    # Repeated start must be safe and idempotent
    await service.start()
    assert service.state == BrowserServiceState.RUNNING
    assert mock_pw.chromium.launch_count == 1  # Did not launch again


@pytest.mark.anyio
async def test_service_shutdown_and_idempotency() -> None:
    mock_pw, factory = create_mock_playwright_factory()
    service = BrowserService(playwright_launcher=factory)

    await service.start()
    session = await service.create_session()
    assert service.active_session_count == 1

    await service.stop()
    assert service.state == BrowserServiceState.STOPPED
    assert service.is_running is False
    assert service.active_session_count == 0
    assert session.is_active() is False
    assert mock_pw.stopped is True

    # Repeated stop must be safe and idempotent
    await service.stop()
    assert service.state == BrowserServiceState.STOPPED


# ==============================================================================
# 3. Startup Failures: Missing Binary and Generic Failure
# ==============================================================================


@pytest.mark.anyio
async def test_startup_missing_binary_raises_structured_error() -> None:
    mock_pw, factory = create_mock_playwright_factory()
    mock_pw.chromium.should_fail = True
    mock_pw.chromium.fail_error = RuntimeError(
        "BrowserType.launch: Executable doesn't exist at chrome-headless-shell.exe\n"
        "Please run the following command to download new browsers: playwright install"
    )

    service = BrowserService(playwright_launcher=factory)

    with pytest.raises(BrowserBinaryMissingError) as exc_info:
        await service.start()

    assert service.state == BrowserServiceState.FAILED
    assert "playwright install" in str(exc_info.value)
    assert mock_pw.stopped is True  # Cleaned up partial instance


@pytest.mark.anyio
async def test_startup_generic_failure_raises_startup_error() -> None:
    mock_pw, factory = create_mock_playwright_factory()
    mock_pw.chromium.should_fail = True
    mock_pw.chromium.fail_error = RuntimeError("Out of system memory (simulated)")

    service = BrowserService(playwright_launcher=factory)

    with pytest.raises(BrowserStartupError) as exc_info:
        await service.start()

    assert service.state == BrowserServiceState.FAILED
    assert "Out of system memory" in str(exc_info.value)
    assert mock_pw.stopped is True


# ==============================================================================
# 4. Session Creation, Isolation, and Limits
# ==============================================================================


@pytest.mark.anyio
async def test_create_session_requires_running_service() -> None:
    _, factory = create_mock_playwright_factory()
    service = BrowserService(playwright_launcher=factory)

    with pytest.raises(BrowserLifecycleError):
        await service.create_session()


@pytest.mark.anyio
async def test_session_creation_isolation_and_security_settings() -> None:
    mock_pw, factory = create_mock_playwright_factory()
    service = BrowserService(playwright_launcher=factory)
    await service.start()

    session1 = await service.create_session()
    session2 = await service.create_session()

    assert session1.session_id != session2.session_id
    assert session1.context is not session2.context
    assert service.active_session_count == 2

    # Verify security flags passed to new_context
    browser = mock_pw.chromium.last_browser
    assert browser is not None
    assert len(browser.contexts) == 2

    for ctx in browser.contexts:
        # Critical security check: ignore_https_errors must NEVER be True
        assert ctx.options.get("ignore_https_errors") is False
        assert ctx.options.get("java_script_enabled") is True


@pytest.mark.anyio
async def test_session_limit_exceeded_raises_error() -> None:
    _, factory = create_mock_playwright_factory()
    service = BrowserService(max_sessions=2, playwright_launcher=factory)
    await service.start()

    _ = await service.create_session()
    _ = await service.create_session()
    assert service.active_session_count == 2

    # Third session must fail
    with pytest.raises(BrowserSessionLimitError) as exc_info:
        await service.create_session()

    assert "maximum concurrent sessions" in str(exc_info.value)
    assert service.active_session_count == 2


@pytest.mark.anyio
async def test_session_creation_failure_does_not_leak_session_count() -> None:
    mock_pw, factory = create_mock_playwright_factory()
    service = BrowserService(max_sessions=2, playwright_launcher=factory)
    await service.start()

    browser = mock_pw.chromium.last_browser
    assert browser is not None
    browser.fail_new_context = True

    with pytest.raises(BrowserSessionCreationError):
        await service.create_session()

    assert service.active_session_count == 0


# ==============================================================================
# 5. Session Retrieval, Closing, and Idle Cleanup
# ==============================================================================


@pytest.mark.anyio
async def test_get_and_close_session() -> None:
    _, factory = create_mock_playwright_factory()
    service = BrowserService(playwright_launcher=factory)
    await service.start()

    session = await service.create_session()
    sid = session.session_id

    # Lookup
    retrieved = await service.get_session(sid)
    assert retrieved is session
    assert await service.get_session("unknown_id") is None

    # Explicit close via service
    closed = await service.close_session(sid)
    assert closed is True
    assert service.active_session_count == 0
    assert session.is_active() is False

    # Closing nonexistent is safe
    assert await service.close_session(sid) is False


@pytest.mark.anyio
async def test_session_closing_itself_unregisters_from_service() -> None:
    _, factory = create_mock_playwright_factory()
    service = BrowserService(playwright_launcher=factory)
    await service.start()

    session = await service.create_session()
    assert service.active_session_count == 1

    await session.close()
    assert service.active_session_count == 0
    assert await service.get_session(session.session_id) is None


@pytest.mark.anyio
async def test_cleanup_idle_sessions() -> None:
    _, factory = create_mock_playwright_factory()
    service = BrowserService(idle_timeout_seconds=30.0, playwright_launcher=factory)
    await service.start()

    active_session = await service.create_session()
    idle_session = await service.create_session()

    # Backdate idle session
    idle_session._last_accessed_at -= 60.0

    cleaned = await service.cleanup_idle_sessions()
    assert cleaned == 1
    assert service.active_session_count == 1
    assert active_session.is_active() is True
    assert idle_session.is_active() is False


# ==============================================================================
# 6. Concurrency Safety
# ==============================================================================


@pytest.mark.anyio
async def test_concurrent_session_creation() -> None:
    _, factory = create_mock_playwright_factory()
    service = BrowserService(max_sessions=5, playwright_launcher=factory)
    await service.start()

    # Launch 5 concurrent session creations
    sessions = await asyncio.gather(*[service.create_session() for _ in range(5)])

    assert len(sessions) == 5
    assert service.active_session_count == 5
    unique_ids = {s.session_id for s in sessions}
    assert len(unique_ids) == 5
