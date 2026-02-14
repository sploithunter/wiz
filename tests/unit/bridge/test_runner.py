"""Tests for session runner."""

from unittest.mock import MagicMock

from wiz.bridge.client import BridgeClient
from wiz.bridge.monitor import BridgeEventMonitor
from wiz.bridge.runner import SessionRunner


class TestSessionRunner:
    def _make_runner(self, client=None, monitor=None, cleanup_on_start=False):
        client = client or MagicMock(spec=BridgeClient)
        monitor = monitor or MagicMock(spec=BridgeEventMonitor)
        return SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=cleanup_on_start,
        )

    def test_full_lifecycle_success(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = "sess-1"
        client.send_prompt.return_value = True
        client.get_session.return_value = {"status": "idle"}

        monitor = MagicMock(spec=BridgeEventMonitor)
        monitor.stop_detected = False
        monitor.wait_for_stop.return_value = False
        monitor.events = []
        # Simulate idle detection on first poll by returning stop on second call
        call_count = [0]

        def fake_get_session(sid):
            call_count[0] += 1
            if call_count[0] >= 1:
                return {"status": "idle"}
            return {"status": "working"}

        client.get_session.side_effect = fake_get_session

        runner = SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=False,
        )
        result = runner.run("test", "/tmp", "do stuff", timeout=5)

        assert result.success is True
        assert result.reason == "completed"
        client.create_session.assert_called_once()
        client.send_prompt.assert_called_once_with("sess-1", "do stuff")
        client.delete_session.assert_called_once_with("sess-1")

    def test_bridge_unavailable(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = False
        monitor = MagicMock(spec=BridgeEventMonitor)

        runner = self._make_runner(client, monitor)
        result = runner.run("test", "/tmp", "prompt")
        assert result.success is False
        assert result.reason == "bridge_unavailable"

    def test_session_creation_failure(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = None
        monitor = MagicMock(spec=BridgeEventMonitor)

        runner = self._make_runner(client, monitor)
        result = runner.run("test", "/tmp", "prompt")
        assert result.success is False
        assert result.reason == "failed_to_create_session"

    def test_prompt_send_failure(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = "sess-1"
        client.send_prompt.return_value = False
        monitor = MagicMock(spec=BridgeEventMonitor)

        runner = self._make_runner(client, monitor)
        result = runner.run("test", "/tmp", "prompt")
        assert result.success is False
        assert result.reason == "failed_to_send_prompt"
        # Should still cleanup
        client.delete_session.assert_called_once_with("sess-1")

    def test_timeout_path(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = "sess-1"
        client.send_prompt.return_value = True
        client.get_session.return_value = {"status": "working"}

        monitor = MagicMock(spec=BridgeEventMonitor)
        monitor.stop_detected = False
        monitor.wait_for_stop.return_value = False
        monitor.events = []

        runner = SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=False,
        )
        result = runner.run("test", "/tmp", "prompt", timeout=0.05)

        assert result.success is False
        assert result.reason == "timeout"
        client.delete_session.assert_called_once()

    def test_stop_event_path(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = "sess-1"
        client.send_prompt.return_value = True

        monitor = MagicMock(spec=BridgeEventMonitor)
        monitor.stop_detected = True
        monitor.wait_for_stop.return_value = True
        monitor.events = [{"type": "event", "data": {"type": "stop"}}]

        runner = SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=False,
        )
        result = runner.run("test", "/tmp", "prompt")

        assert result.success is True
        assert result.reason == "completed"

    def test_offline_detection(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = "sess-1"
        client.send_prompt.return_value = True
        client.get_session.return_value = {"status": "offline"}

        monitor = MagicMock(spec=BridgeEventMonitor)
        monitor.stop_detected = False
        monitor.wait_for_stop.return_value = False
        monitor.events = []

        runner = SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=False,
        )
        result = runner.run("test", "/tmp", "prompt", timeout=5)

        assert result.success is True
        assert result.reason == "completed"

    def test_cleanup_on_exception(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = "sess-1"
        client.send_prompt.side_effect = RuntimeError("unexpected")
        monitor = MagicMock(spec=BridgeEventMonitor)

        runner = self._make_runner(client, monitor)
        try:
            runner.run("test", "/tmp", "prompt")
        except RuntimeError:
            pass
        client.delete_session.assert_called_once_with("sess-1")

    def test_startup_cleanup_runs_once(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = "sess-1"
        client.send_prompt.return_value = True
        client.get_session.return_value = {"status": "idle"}
        client.cleanup_all_sessions.return_value = 5

        monitor = MagicMock(spec=BridgeEventMonitor)
        monitor.stop_detected = False
        monitor.wait_for_stop.return_value = False
        monitor.events = []

        runner = SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=True,
        )
        runner.run("test", "/tmp", "prompt", timeout=5)
        runner.run("test2", "/tmp", "prompt2", timeout=5)

        # cleanup_all_sessions called once (first run only)
        client.cleanup_all_sessions.assert_called_once()

    def test_startup_cleanup_disabled(self):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = "sess-1"
        client.send_prompt.return_value = True
        client.get_session.return_value = {"status": "idle"}

        monitor = MagicMock(spec=BridgeEventMonitor)
        monitor.stop_detected = False
        monitor.wait_for_stop.return_value = False
        monitor.events = []

        runner = SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=False,
        )
        runner.run("test", "/tmp", "prompt", timeout=5)
        client.cleanup_all_sessions.assert_not_called()
