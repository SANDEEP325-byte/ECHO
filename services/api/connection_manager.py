"""WebSocket Connection Manager (Phase 10C.1).

Manages active WebSocket client connections, session-isolated routing,
broadcasts, and orderly shutdown cleanup.
"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket

from packages.interfaces.events import InterfaceEvent
from services.configuration.lifecycle import lifecycle_manager
from services.logging.logger import logger  # type: ignore[attr-defined]


class ConnectionManager:
    """Manages active WebSocket connections grouped by session ID."""

    def __init__(self) -> None:
        self._sessions: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        # Register clean shutdown with global runtime lifecycle
        lifecycle_manager.register_cleanup(self.close_all)

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Register an active, already-accepted WebSocket connection."""
        async with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = set()
            self._sessions[session_id].add(websocket)
            logger.info(
                "WebSocket connected for session: {} (total session sockets: {})",
                session_id,
                len(self._sessions[session_id]),
            )

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """Unregister a disconnected WebSocket connection."""
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].discard(websocket)
                if not self._sessions[session_id]:
                    del self._sessions[session_id]
            logger.info("WebSocket disconnected for session: {}", session_id)

    async def send_event(self, session_id: str, event: InterfaceEvent) -> None:
        """Dispatch an event to all active sockets belonging to a specific session."""
        async with self._lock:
            sockets = list(self._sessions.get(session_id, set()))

        if not sockets:
            logger.debug("No active sockets for session {}; event not delivered.", session_id)
            return

        payload_dict = event.model_dump()
        dead_sockets: list[WebSocket] = []

        for ws in sockets:
            try:
                await ws.send_json(payload_dict)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to send event to socket in session {}: {}", session_id, exc)
                dead_sockets.append(ws)

        if dead_sockets:
            async with self._lock:
                if session_id in self._sessions:
                    for dead in dead_sockets:
                        self._sessions[session_id].discard(dead)
                    if not self._sessions[session_id]:
                        del self._sessions[session_id]

    async def broadcast_event(self, event: InterfaceEvent) -> None:
        """Broadcast an event across all connected sessions."""
        async with self._lock:
            all_sockets = [ws for socket_set in self._sessions.values() for ws in socket_set]

        if not all_sockets:
            return

        payload_dict = event.model_dump()
        for ws in all_sockets:
            try:
                await ws.send_json(payload_dict)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Broadcast send failure: {}", exc)

    async def close_all(self, code: int = 1001, reason: str = "Server shutting down") -> None:
        """Close all open WebSocket connections gracefully during shutdown."""
        async with self._lock:
            all_sockets = [ws for socket_set in self._sessions.values() for ws in socket_set]
            self._sessions.clear()

        logger.info("Closing {} active WebSocket connections...", len(all_sockets))
        for ws in all_sockets:
            try:
                await ws.close(code=code, reason=reason)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Socket close note: {}", exc)

    def get_session_count(self) -> int:
        """Return the count of unique active sessions."""
        return len(self._sessions)

    def get_connection_count(self, session_id: str | None = None) -> int:
        """Return total connections, or connections for a specific session."""
        if session_id is not None:
            return len(self._sessions.get(session_id, set()))
        return sum(len(s) for s in self._sessions.values())


# Global singleton connection manager
connection_manager = ConnectionManager()
