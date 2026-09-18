"""ECHO Browser Async Runner.

Provides a dedicated, thread-safe background event loop and runner for synchronous
ECHO components (such as Tool.execute()) to execute asynchronous Playwright
browser operations without event-loop collision or Playwright thread-binding violations.
"""

import asyncio
import concurrent.futures
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from services.browser.errors import BrowserTimeoutError
from services.logging.logger import logger  # type: ignore[attr-defined]

T = TypeVar("T")


class BrowserAsyncRunner:
    """Manages a dedicated background thread and asyncio event loop for browser operations."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        self._is_running = False

    def start(self) -> None:
        """Start the background event loop thread if not already running."""
        with self._lock:
            if self._is_running and self._loop is not None and self._loop.is_running():
                return

            self._ready_event.clear()
            self._thread = threading.Thread(
                target=self._run_event_loop,
                name="ECHOBrowserWorker",
                daemon=True,
            )
            self._thread.start()
            self._ready_event.wait(timeout=5.0)

    def _run_event_loop(self) -> None:
        """Worker thread entry point: runs the private event loop forever."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._is_running = True
        self._ready_event.set()

        try:
            self._loop.run_forever()
        finally:
            self._is_running = False
            # Cancel remaining tasks
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()
            self._loop = None

    def stop(self, timeout_seconds: float = 5.0) -> None:
        """Cleanly stop the background event loop and join the worker thread."""
        with self._lock:
            if not self._is_running or self._loop is None:
                return

            loop = self._loop
            loop.call_soon_threadsafe(loop.stop)

            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=timeout_seconds)

            self._is_running = False
            self._thread = None
            self._loop = None

    def run(self, coro: Coroutine[Any, Any, T], timeout_seconds: float = 65.0) -> T:
        """Submit an async coroutine to the browser event loop and block for the result.

        Thread-safe and callable from any thread.
        """
        if not self._is_running or self._loop is None:
            self.start()

        if self._loop is None:
            raise RuntimeError("Failed to start browser event loop worker thread.")

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            logger.error("Browser operation timed out after %s seconds.", timeout_seconds)
            raise BrowserTimeoutError(
                f"Browser operation timed out after {timeout_seconds} seconds."
            ) from exc
        except Exception:
            # Let the original exception propagate directly
            raise


browser_runner = BrowserAsyncRunner()
