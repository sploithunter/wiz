"""WebSocket event monitor for Coding Agent Bridge.

Pattern adapted from harness-bench cab_bridge.py:101-148.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import websocket

logger = logging.getLogger(__name__)


class BridgeEventMonitor:
    """WebSocket client that connects to bridge and captures events."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4003",
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.on_event = on_event
        self._ws: websocket.WebSocketApp | None = None
        self._ws_thread: threading.Thread | None = None
        self._events: list[dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._connected = threading.Event()

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @property
    def stop_detected(self) -> bool:
        return self._stop_event.is_set()

    def start(self) -> None:
        """Start WebSocket connection for real-time events."""
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")

        def on_message(ws: Any, message: str) -> None:
            try:
                data = json.loads(message)
                self._events.append(data)

                if self.on_event:
                    self.on_event(data)

                # Check for completion events
                if data.get("type") == "event":
                    event_data = data.get("data", {})
                    if event_data.get("type") in ("stop", "session_end"):
                        self._stop_event.set()
            except Exception as e:
                logger.warning("WebSocket message error: %s", e)

        def on_error(ws: Any, error: Any) -> None:
            logger.warning("WebSocket error: %s", error)

        def on_close(ws: Any, close_status_code: Any, close_msg: Any) -> None:
            logger.debug("WebSocket closed")

        def on_open(ws: Any) -> None:
            logger.debug("WebSocket connected")
            self._connected.set()

        self._ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )

        self._ws_thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._ws_thread.start()

    def stop(self) -> None:
        """Stop WebSocket connection."""
        if self._ws:
            self._ws.close()
            self._ws = None

    def wait_for_stop(self, timeout: float | None = None) -> bool:
        """Wait for a stop event. Returns True if stop detected, False on timeout."""
        return self._stop_event.wait(timeout=timeout)

    def clear(self) -> None:
        """Clear events and stop event."""
        self._events = []
        self._stop_event.clear()
        self._connected.clear()
