"""Tests for bridge event monitor."""

import json
from unittest.mock import patch

from wiz.bridge.monitor import BridgeEventMonitor


class TestBridgeEventMonitor:
    def test_event_capture(self):
        monitor = BridgeEventMonitor()
        # Simulate on_message callback directly
        msg = json.dumps({"type": "event", "data": {"type": "pre_tool_use", "tool": "Bash"}})

        # Access the internal handler by simulating start
        with patch("wiz.bridge.monitor.websocket.WebSocketApp") as mock_ws:
            monitor.start()
            # Get the on_message callback
            on_message = mock_ws.call_args[1]["on_message"]
            on_message(None, msg)

        assert len(monitor.events) == 1
        assert monitor.events[0]["type"] == "event"

    def test_stop_detection(self):
        monitor = BridgeEventMonitor()
        stop_msg = json.dumps({"type": "event", "data": {"type": "stop"}})

        with patch("wiz.bridge.monitor.websocket.WebSocketApp") as mock_ws:
            monitor.start()
            on_message = mock_ws.call_args[1]["on_message"]
            on_message(None, stop_msg)

        assert monitor.stop_detected is True

    def test_session_end_detection(self):
        monitor = BridgeEventMonitor()
        msg = json.dumps({"type": "event", "data": {"type": "session_end"}})

        with patch("wiz.bridge.monitor.websocket.WebSocketApp") as mock_ws:
            monitor.start()
            on_message = mock_ws.call_args[1]["on_message"]
            on_message(None, msg)

        assert monitor.stop_detected is True

    def test_non_stop_event_does_not_trigger(self):
        monitor = BridgeEventMonitor()
        msg = json.dumps({"type": "event", "data": {"type": "pre_tool_use"}})

        with patch("wiz.bridge.monitor.websocket.WebSocketApp") as mock_ws:
            monitor.start()
            on_message = mock_ws.call_args[1]["on_message"]
            on_message(None, msg)

        assert monitor.stop_detected is False

    def test_user_callback(self):
        received = []
        monitor = BridgeEventMonitor(on_event=lambda e: received.append(e))
        msg = json.dumps({"type": "init", "data": {}})

        with patch("wiz.bridge.monitor.websocket.WebSocketApp") as mock_ws:
            monitor.start()
            on_message = mock_ws.call_args[1]["on_message"]
            on_message(None, msg)

        assert len(received) == 1

    def test_clear(self):
        monitor = BridgeEventMonitor()
        monitor._events = [{"test": True}]
        monitor._stop_event.set()
        monitor.clear()
        assert monitor.events == []
        assert monitor.stop_detected is False

    def test_wait_for_stop_timeout(self):
        monitor = BridgeEventMonitor()
        result = monitor.wait_for_stop(timeout=0.01)
        assert result is False

    def test_invalid_json_handled(self):
        monitor = BridgeEventMonitor()

        with patch("wiz.bridge.monitor.websocket.WebSocketApp") as mock_ws:
            monitor.start()
            on_message = mock_ws.call_args[1]["on_message"]
            on_message(None, "not json")

        # Should not crash, no events captured
        assert len(monitor.events) == 0
