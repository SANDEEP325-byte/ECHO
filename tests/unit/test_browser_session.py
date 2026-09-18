"""Unit tests for ECHO BrowserSession (Phase 5B).

Tests session lifecycle, isolation, page management, timeouts, and safe cleanup.
100% offline, deterministic, and isolated using mock context/pages.
"""

import pytest

from services.browser.errors import BrowserSessionClosedError
from services.browser.session import BrowserSession, BrowserSessionState


class DummyPage:
    """Mock Playwright Page for session testing."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class DummyContext:
    """Mock Playwright BrowserContext for session testing."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_session_initialization() -> None:
    context = DummyContext()
    page = DummyPage()
    session = BrowserSession(
        session_id="test_session_1",
        context=context,
        primary_page=page,
        timeout_ms=15000,
    )

    assert session.session_id == "test_session_1"
    assert session.state == BrowserSessionState.ACTIVE
    assert session.is_active() is True
    assert session.timeout_ms == 15000
    assert session.context is context
    assert session.primary_page is page
    assert session.created_at <= session.last_accessed_at


@pytest.mark.anyio
async def test_session_touch_updates_timestamp() -> None:
    session = BrowserSession(
        session_id="test_session_touch",
        context=DummyContext(),
        primary_page=DummyPage(),
    )

    initial_time = session.last_accessed_at
    # Backdate to simulate prior access
    session._last_accessed_at = initial_time - 5.0
    session.touch()
    assert session.last_accessed_at >= initial_time


@pytest.mark.anyio
async def test_session_expiration_check() -> None:
    session = BrowserSession(
        session_id="test_session_exp",
        context=DummyContext(),
        primary_page=DummyPage(),
    )

    assert session.is_expired(idle_timeout_seconds=10.0) is False
    # Manually backdate last_accessed_at to simulate idle duration
    session._last_accessed_at = session._last_accessed_at - 20.0
    assert session.is_expired(idle_timeout_seconds=10.0) is True


@pytest.mark.anyio
async def test_session_close_lifecycle_and_callback() -> None:
    context = DummyContext()
    page = DummyPage()
    closed_callback_invoked = False
    callback_session_id = None

    async def on_close_callback(sid: str) -> None:
        nonlocal closed_callback_invoked, callback_session_id
        closed_callback_invoked = True
        callback_session_id = sid

    session = BrowserSession(
        session_id="test_session_close",
        context=context,
        primary_page=page,
        on_close=on_close_callback,
    )

    assert session.is_active() is True
    await session.close()

    assert session.state == BrowserSessionState.CLOSED
    assert session.is_active() is False
    assert page.closed is True
    assert context.closed is True
    assert closed_callback_invoked is True
    assert callback_session_id == "test_session_close"


@pytest.mark.anyio
async def test_session_repeated_close_is_safe() -> None:
    context = DummyContext()
    page = DummyPage()
    call_count = 0

    async def on_close_callback(sid: str) -> None:
        nonlocal call_count
        call_count += 1

    session = BrowserSession(
        session_id="test_session_rep_close",
        context=context,
        primary_page=page,
        on_close=on_close_callback,
    )

    await session.close()
    await session.close()  # Repeated call must be safe no-op

    assert session.state == BrowserSessionState.CLOSED
    assert call_count == 1


@pytest.mark.anyio
async def test_accessing_closed_session_raises_structured_error() -> None:
    session = BrowserSession(
        session_id="test_session_closed_err",
        context=DummyContext(),
        primary_page=DummyPage(),
    )
    await session.close()

    with pytest.raises(BrowserSessionClosedError) as exc_context:
        _ = session.context
    assert "is closed" in str(exc_context.value)

    with pytest.raises(BrowserSessionClosedError) as exc_page:
        _ = session.primary_page
    assert "is closed" in str(exc_page.value)


@pytest.mark.anyio
async def test_session_close_tolerates_page_or_context_errors() -> None:
    class FailingResource:
        async def close(self) -> None:
            raise RuntimeError("Underlying process crashed")

    session = BrowserSession(
        session_id="test_session_failing_res",
        context=FailingResource(),
        primary_page=FailingResource(),
    )

    # Must not raise unhandled exception
    await session.close()
    assert session.state == BrowserSessionState.CLOSED
