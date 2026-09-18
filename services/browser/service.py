"""ECHO Browser Service (Phase 5B).

Central orchestrator for the Playwright Chromium browser process lifecycle.
Manages browser startup, shutdown, session creation, isolation, bounded resource limits,
and deterministic cleanup.

SECURITY AND LIFECYCLE RULES:
- Zero persistent profiles, cookies, or storage state to disk.
- Minimal safe launch arguments; no --no-sandbox or security disables.
- HTTPS certificate verification is strictly enforced (ignore_https_errors=False).
- Missing Chromium binary raises structured BrowserBinaryMissingError without crashing ECHO.
- All session contexts are isolated from each other.
"""

import asyncio
import uuid
from collections.abc import Callable
from enum import Enum
from typing import Any

from services.browser.errors import (
    BrowserBinaryMissingError,
    BrowserConfigurationError,
    BrowserLifecycleError,
    BrowserSessionCreationError,
    BrowserSessionLimitError,
    BrowserStartupError,
)
from services.browser.policy import BrowserSecurityPolicy, browser_security_policy
from services.browser.session import BrowserSession
from services.logging.logger import logger  # type: ignore[attr-defined]


class BrowserServiceState(str, Enum):
    """Lifecycle states of BrowserService."""

    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class BrowserService:
    """Orchestrates Playwright and Chromium process lifecycle for ECHO."""

    MIN_TIMEOUT_MS = 1000
    MAX_TIMEOUT_MS = 120000
    MIN_SESSIONS = 1
    MAX_SESSIONS_LIMIT = 20
    MIN_IDLE_TIMEOUT = 10.0
    MAX_IDLE_TIMEOUT = 86400.0

    def __init__(
        self,
        headless: bool = True,
        startup_timeout_ms: int = 30000,
        default_timeout_ms: int = 30000,
        max_sessions: int = 5,
        idle_timeout_seconds: float = 300.0,
        security_policy: BrowserSecurityPolicy | None = None,
        playwright_launcher: Callable[[], Any] | None = None,
    ) -> None:
        # Validate configuration values
        self._validate_config(
            startup_timeout_ms=startup_timeout_ms,
            default_timeout_ms=default_timeout_ms,
            max_sessions=max_sessions,
            idle_timeout_seconds=idle_timeout_seconds,
        )

        self.headless = headless
        self.startup_timeout_ms = startup_timeout_ms
        self.default_timeout_ms = default_timeout_ms
        self.max_sessions = max_sessions
        self.idle_timeout_seconds = idle_timeout_seconds
        self.security_policy = security_policy or browser_security_policy
        self._playwright_launcher = playwright_launcher

        self._state = BrowserServiceState.NOT_STARTED
        self._playwright_cm: Any = None
        self._playwright: Any = None
        self._browser: Any = None
        self._sessions: dict[str, BrowserSession] = {}

        self._lifecycle_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()

    @classmethod
    def _validate_config(
        cls,
        startup_timeout_ms: int,
        default_timeout_ms: int,
        max_sessions: int,
        idle_timeout_seconds: float,
    ) -> None:
        """Validate timeout and session limit boundaries."""
        if not (cls.MIN_TIMEOUT_MS <= startup_timeout_ms <= cls.MAX_TIMEOUT_MS):
            raise BrowserConfigurationError(
                f"startup_timeout_ms must be between {cls.MIN_TIMEOUT_MS} and {cls.MAX_TIMEOUT_MS} ms."
            )
        if not (cls.MIN_TIMEOUT_MS <= default_timeout_ms <= cls.MAX_TIMEOUT_MS):
            raise BrowserConfigurationError(
                f"default_timeout_ms must be between {cls.MIN_TIMEOUT_MS} and {cls.MAX_TIMEOUT_MS} ms."
            )
        if not (cls.MIN_SESSIONS <= max_sessions <= cls.MAX_SESSIONS_LIMIT):
            raise BrowserConfigurationError(
                f"max_sessions must be between {cls.MIN_SESSIONS} and {cls.MAX_SESSIONS_LIMIT}."
            )
        if not (cls.MIN_IDLE_TIMEOUT <= idle_timeout_seconds <= cls.MAX_IDLE_TIMEOUT):
            raise BrowserConfigurationError(
                f"idle_timeout_seconds must be between {cls.MIN_IDLE_TIMEOUT} and {cls.MAX_IDLE_TIMEOUT} seconds."
            )

    @property
    def state(self) -> BrowserServiceState:
        """Current lifecycle state of the service."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Check if browser service is running and ready for operations."""
        return self._state == BrowserServiceState.RUNNING

    @property
    def active_session_count(self) -> int:
        """Count of currently registered active sessions."""
        return len(self._sessions)

    async def start(self) -> None:
        """Start Playwright runtime and launch Chromium browser process.

        Idempotent: if service is already RUNNING, returns immediately.
        Fails safely if Chromium is missing or startup fails.
        """
        async with self._lifecycle_lock:
            if self._state == BrowserServiceState.RUNNING:
                logger.debug("BrowserService is already running.")
                return

            if self._state in (BrowserServiceState.STARTING, BrowserServiceState.STOPPING):
                raise BrowserLifecycleError(
                    f"Cannot start BrowserService while it is in '{self._state.value}' state."
                )

            self._state = BrowserServiceState.STARTING
            logger.info("Starting BrowserService (headless=%s)...", self.headless)

            try:
                # 1. Start Playwright
                if self._playwright_launcher is not None:
                    # Injected launcher for deterministic unit tests
                    launcher_res = self._playwright_launcher()
                    if asyncio.iscoroutine(launcher_res):
                        self._playwright = await launcher_res
                    else:
                        self._playwright = launcher_res
                else:
                    from playwright.async_api import async_playwright

                    self._playwright_cm = async_playwright()
                    self._playwright = await self._playwright_cm.start()

                # 2. Launch Chromium browser process
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    timeout=self.startup_timeout_ms,
                )

                self._state = BrowserServiceState.RUNNING
                logger.info("BrowserService successfully started.")

            except Exception as exc:
                self._state = BrowserServiceState.FAILED
                error_msg = str(exc)

                # Safe teardown of partial Playwright instance
                await self._teardown_playwright()

                # Detect missing Chromium binary specifically
                if "Executable doesn't exist" in error_msg or "playwright install" in error_msg:
                    logger.error("Chromium browser binary is not installed: %s", exc)
                    raise BrowserBinaryMissingError() from exc

                logger.error("BrowserService failed to start: %s", exc)
                raise BrowserStartupError(f"Failed to launch browser: {exc}") from exc

    async def _teardown_playwright(self) -> None:
        """Internal helper to safely tear down Playwright instance without raising."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error closing browser during teardown: %s", exc)
            finally:
                self._browser = None

        if self._playwright_cm is not None:
            try:
                await self._playwright_cm.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error stopping playwright context manager: %s", exc)
            finally:
                self._playwright_cm = None
                self._playwright = None
        elif self._playwright is not None:
            try:
                if hasattr(self._playwright, "stop"):
                    await self._playwright.stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error stopping playwright instance: %s", exc)
            finally:
                self._playwright = None

    async def stop(self) -> None:
        """Stop BrowserService, closing all active sessions and the browser process.

        Idempotent: calling stop on an already stopped service is a safe no-op.
        """
        async with self._lifecycle_lock:
            if self._state in (BrowserServiceState.STOPPED, BrowserServiceState.NOT_STARTED):
                return

            self._state = BrowserServiceState.STOPPING
            logger.info("Stopping BrowserService...")

            # 1. Close all active sessions
            async with self._session_lock:
                active_sessions = list(self._sessions.values())
                self._sessions.clear()

            for session in active_sessions:
                try:
                    await session.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Error closing session '%s' during shutdown: %s", session.session_id, exc
                    )

            # 2. Teardown browser and Playwright
            await self._teardown_playwright()

            self._state = BrowserServiceState.STOPPED
            logger.info("BrowserService stopped successfully.")

    async def create_session(self) -> BrowserSession:
        """Create a new isolated BrowserSession.

        Enforces:
        - Service must be RUNNING.
        - max_sessions limit.
        - Ephemeral context (no persistent profile or cookies).
        - ignore_https_errors = False (TLS verification enforced).
        """
        if not self.is_running:
            raise BrowserLifecycleError(
                f"Cannot create session: BrowserService is {self._state.value} (must be running)."
            )

        async with self._session_lock:
            if len(self._sessions) >= self.max_sessions:
                raise BrowserSessionLimitError(
                    f"Cannot create session: maximum concurrent sessions ({self.max_sessions}) reached."
                )

            session_id = f"session_{uuid.uuid4().hex[:12]}"
            context = None
            page = None

            try:
                # Create isolated browser context
                context = await self._browser.new_context(
                    ignore_https_errors=False,  # CRITICAL: Always verify TLS certificates
                    java_script_enabled=True,
                    viewport={"width": 1280, "height": 720},
                )
                if hasattr(context, "set_default_timeout"):
                    context.set_default_timeout(self.default_timeout_ms)

                # Create primary page
                page = await context.new_page()

                # Wrap in BrowserSession
                session = BrowserSession(
                    session_id=session_id,
                    context=context,
                    primary_page=page,
                    timeout_ms=self.default_timeout_ms,
                    on_close=self._on_session_closed,
                )

                self._sessions[session_id] = session
                logger.info(
                    "Created browser session '%s' (active: %d).", session_id, len(self._sessions)
                )
                return session

            except Exception as exc:
                # Cleanup partially created context
                if context is not None:
                    try:
                        await context.close()
                    except Exception as close_exc:  # noqa: BLE001
                        logger.debug(
                            "Error closing context after session creation failure: %s", close_exc
                        )
                logger.error("Failed to create browser session: %s", exc)
                raise BrowserSessionCreationError(
                    f"Failed to create browser session context: {exc}"
                ) from exc

    async def get_session(self, session_id: str) -> BrowserSession | None:
        """Retrieve an active session by ID and update its last activity timestamp."""
        async with self._session_lock:
            session = self._sessions.get(session_id)
            if session is not None and session.is_active():
                session.touch()
                return session
            return None

    async def close_session(self, session_id: str) -> bool:
        """Explicitly close a session by ID and unregister it."""
        session = None
        async with self._session_lock:
            session = self._sessions.get(session_id)

        if session is not None:
            await session.close()
            return True
        return False

    async def _on_session_closed(self, session_id: str) -> None:
        """Callback invoked by BrowserSession when it completes closing."""
        async with self._session_lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.debug("Unregistered closed browser session '%s'.", session_id)

    async def cleanup_idle_sessions(self) -> int:
        """Scan active sessions and close those exceeding idle_timeout_seconds.

        Returns count of closed idle sessions.
        """
        async with self._session_lock:
            expired_sessions = [
                s for s in self._sessions.values() if s.is_expired(self.idle_timeout_seconds)
            ]

        closed_count = 0
        for session in expired_sessions:
            try:
                await session.close()
                closed_count += 1
                logger.info("Closed idle browser session '%s'.", session.session_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error closing idle session '%s': %s", session.session_id, exc)

        return closed_count
