"""Runtime Lifecycle Management (Phase 10A).

Provides centralized, graceful, and idempotent shutdown handling for ECHO.
Ensures resources (browser sessions, audio streams, memory connections) are cleanly
stopped without leaking system processes or corrupting SQLite state.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable
from typing import Any

from services.logging.logger import logger  # type: ignore[attr-defined]


class RuntimeLifecycle:
    """Coordinates clean, idempotent runtime shutdown across all ECHO subsystems."""

    def __init__(self) -> None:
        self._shutdown_called = False
        self._lock = threading.Lock()
        self._cleanups: list[Callable[[], Any]] = []

    @property
    def is_shutting_down(self) -> bool:
        """Return True if shutdown has been initiated."""
        return self._shutdown_called

    def register_cleanup(self, callback: Callable[[], Any]) -> None:
        """Register a sync or async cleanup function to be invoked on shutdown."""
        with self._lock:
            if callback not in self._cleanups:
                self._cleanups.append(callback)

    async def shutdown(self) -> None:
        """Perform orderly, asynchronous shutdown of all active services."""
        with self._lock:
            if self._shutdown_called:
                logger.debug("Shutdown already called; skipping duplicate invocation.")
                return
            self._shutdown_called = True
            cleanups_to_run = list(self._cleanups)

        logger.info("Initiating graceful ECHO runtime shutdown...")

        # 1. Run registered cleanup hooks
        for cb in cleanups_to_run:
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb()
                else:
                    res = cb()
                    if inspect.isawaitable(res):
                        await res
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error running registered cleanup hook: {}", exc)

        # 2. Cleanly stop BrowserService if active
        try:
            from services.browser.service import browser_service

            if getattr(browser_service, "is_running", False):
                logger.info("Stopping active browser sessions...")
                await browser_service.stop()
                logger.info("BrowserService stopped successfully.")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Browser service shutdown note: {}", exc)

        # 3. Release Audio / Voice resources if active
        try:
            import sounddevice as sd  # type: ignore[import-untyped]

            sd.stop()
        except Exception:  # noqa: BLE001, S110
            pass

        logger.info("ECHO runtime shutdown complete.")

    def shutdown_sync(self) -> None:
        """Synchronous wrapper for shutdown, suitable for signal handlers and atexit."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule task if event loop is already running
                asyncio.create_task(self.shutdown())
            else:
                loop.run_until_complete(self.shutdown())
        except RuntimeError:
            # Fallback if no event loop in thread
            asyncio.run(self.shutdown())
        except Exception as exc:  # noqa: BLE001
            logger.debug("Synchronous shutdown notice: {}", exc)


# Global lifecycle manager singleton
lifecycle_manager = RuntimeLifecycle()
