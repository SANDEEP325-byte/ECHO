"""ECHO Browser Session (Phase 5B).

Represents an isolated, ephemeral browser session owning a Playwright BrowserContext
and primary Page. Enforces privacy, session lifecycle states, and bounded resource usage.

SECURITY NOTICE:
Arbitrary JavaScript execution (evaluate/evaluate_handle) and DOM interaction tools
are strictly excluded from this abstraction.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from services.browser.errors import BrowserSessionClosedError
from services.logging.logger import logger  # type: ignore[attr-defined]


class BrowserSessionState(str, Enum):
    """Lifecycle states of a BrowserSession."""

    CREATED = "created"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class BrowserSession:
    """Represents an isolated browser session wrapping a Playwright BrowserContext.

    Guarantees:
    - Ephemeral context: no cookies, tokens, or storage persisted to disk.
    - Explicit lifecycle transitions: CREATED -> ACTIVE -> CLOSING -> CLOSED.
    - Idempotent close handling without resource leaks.
    - Bounded idle detection.
    """

    def __init__(
        self,
        session_id: str,
        context: Any,
        primary_page: Any | None = None,
        timeout_ms: int = 30000,
        on_close: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._session_id = session_id
        self._context = context
        self._primary_page = primary_page
        self._timeout_ms = timeout_ms
        self._on_close = on_close

        self._state = BrowserSessionState.ACTIVE
        self._created_at = time.monotonic()
        self._last_accessed_at = self._created_at
        self._lock = asyncio.Lock()

    @property
    def session_id(self) -> str:
        """Unique identifier for this browser session."""
        return self._session_id

    @property
    def state(self) -> BrowserSessionState:
        """Current lifecycle state of the session."""
        return self._state

    @property
    def created_at(self) -> float:
        """Monotonic timestamp of session creation."""
        return self._created_at

    @property
    def last_accessed_at(self) -> float:
        """Monotonic timestamp of last session activity."""
        return self._last_accessed_at

    @property
    def timeout_ms(self) -> int:
        """Configured default timeout in milliseconds."""
        return self._timeout_ms

    @property
    def context(self) -> Any:
        """Underlying Playwright BrowserContext.

        Raises BrowserSessionClosedError if session is not active.
        """
        if not self.is_active():
            raise BrowserSessionClosedError(
                f"Cannot access browser context: session '{self._session_id}' is {self._state.value}."
            )
        self.touch()
        return self._context

    @property
    def primary_page(self) -> Any:
        """Primary Page associated with this session.

        Raises BrowserSessionClosedError if session is not active.
        """
        if not self.is_active():
            raise BrowserSessionClosedError(
                f"Cannot access page: session '{self._session_id}' is {self._state.value}."
            )
        self.touch()
        return self._primary_page

    def is_active(self) -> bool:
        """Check if the session is currently active and usable."""
        return self._state == BrowserSessionState.ACTIVE

    def is_expired(self, idle_timeout_seconds: float) -> bool:
        """Check if the session has been idle longer than the configured threshold."""
        if not self.is_active():
            return False
        return (time.monotonic() - self._last_accessed_at) > idle_timeout_seconds

    def touch(self) -> None:
        """Update last accessed timestamp to prevent premature idle expiration."""
        if self.is_active():
            self._last_accessed_at = time.monotonic()

    async def close(self) -> None:
        """Safely close browser context and associated pages.

        Idempotent: calling close on an already closed or closing session is a safe no-op.
        """
        async with self._lock:
            if self._state in (BrowserSessionState.CLOSING, BrowserSessionState.CLOSED):
                return

            self._state = BrowserSessionState.CLOSING

            # Close primary page if present
            if self._primary_page is not None:
                try:
                    if hasattr(self._primary_page, "close"):
                        await self._primary_page.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Error closing primary page in session '%s': %s",
                        self._session_id,
                        exc,
                    )
                finally:
                    self._primary_page = None

            # Close context
            if self._context is not None:
                try:
                    if hasattr(self._context, "close"):
                        await self._context.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Error closing browser context in session '%s': %s",
                        self._session_id,
                        exc,
                    )
                finally:
                    self._context = None

            self._state = BrowserSessionState.CLOSED

        # Notify parent service to unregister session
        if self._on_close is not None:
            try:
                await self._on_close(self._session_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Error executing on_close callback for session '%s': %s",
                    self._session_id,
                    exc,
                )
