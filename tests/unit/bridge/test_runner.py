"""Tests for session runner."""

import json
from unittest.mock import MagicMock, patch

from wiz.bridge.client import BridgeClient
from wiz.bridge.monitor import BridgeEventMonitor
from wiz.bridge.runner import SessionRunner, ensure_hooks


# All bridge session tests need ensure_hooks mocked to avoid touching real settings
_MOCK_HOOKS = patch("wiz.bridge.runner.ensure_hooks", return_value=True)


class TestSessionRunner:
    def _make_runner(self, client=None, monitor=None, cleanup_on_start=False):
        client = client or MagicMock(spec=BridgeClient)
        monitor = monitor or MagicMock(spec=BridgeEventMonitor)
        return SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=cleanup_on_start,
        )

    @_MOCK_HOOKS
    def test_full_lifecycle_success(self, _mock_hooks):
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

    @_MOCK_HOOKS
    def test_session_creation_failure(self, _mock_hooks):
        client = MagicMock(spec=BridgeClient)
        client.health_check.return_value = True
        client.create_session.return_value = None
        monitor = MagicMock(spec=BridgeEventMonitor)

        runner = self._make_runner(client, monitor)
        result = runner.run("test", "/tmp", "prompt")
        assert result.success is False
        assert result.reason == "failed_to_create_session"

    @_MOCK_HOOKS
    def test_prompt_send_failure(self, _mock_hooks):
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

    @_MOCK_HOOKS
    def test_timeout_path(self, _mock_hooks):
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

    @_MOCK_HOOKS
    def test_stop_event_path(self, _mock_hooks):
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

    @_MOCK_HOOKS
    def test_offline_detection(self, _mock_hooks):
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

    @_MOCK_HOOKS
    def test_cleanup_on_exception(self, _mock_hooks):
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

    @_MOCK_HOOKS
    def test_startup_cleanup_runs_once(self, _mock_hooks):
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

    @_MOCK_HOOKS
    def test_startup_cleanup_disabled(self, _mock_hooks):
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

    @patch("wiz.bridge.runner.subprocess.run")
    @patch("wiz.bridge.runner.shutil.which", return_value="/usr/bin/codex")
    def test_codex_exec_success(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="done", stderr="")

        runner = self._make_runner()
        result = runner.run("test", "/tmp", "prompt", agent="codex", timeout=30)

        assert result.success is True
        assert result.reason == "completed"
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0][:3] == ["codex", "exec", "--full-auto"]

    @patch("wiz.bridge.runner.shutil.which", return_value=None)
    def test_codex_not_installed(self, mock_which):
        runner = self._make_runner()
        result = runner.run("test", "/tmp", "prompt", agent="codex")

        assert result.success is False
        assert result.reason == "codex_not_installed"

    @patch("wiz.bridge.runner.subprocess.run")
    @patch("wiz.bridge.runner.shutil.which", return_value="/usr/bin/codex")
    def test_codex_exec_failure(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

        runner = self._make_runner()
        result = runner.run("test", "/tmp", "prompt", agent="codex", timeout=30)

        assert result.success is False
        assert result.reason == "exit_code_1"

    @patch("wiz.bridge.runner.subprocess.run")
    @patch("wiz.bridge.runner.shutil.which", return_value="/usr/bin/codex")
    def test_codex_exec_timeout(self, mock_which, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="codex", timeout=5)

        runner = self._make_runner()
        result = runner.run("test", "/tmp", "prompt", agent="codex", timeout=5)

        assert result.success is False
        assert result.reason == "timeout"

    @patch("wiz.bridge.runner.subprocess.run")
    @patch("wiz.bridge.runner.shutil.which", return_value="/usr/bin/codex")
    def test_codex_dispatches_not_bridge(self, mock_which, mock_run):
        """Codex sessions should NOT go through the bridge."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        client = MagicMock(spec=BridgeClient)
        monitor = MagicMock(spec=BridgeEventMonitor)
        runner = SessionRunner(
            client, monitor, init_wait=0.01, poll_interval=0.01,
            cleanup_on_start=False,
        )
        runner.run("test", "/tmp", "prompt", agent="codex", timeout=30)

        # Bridge should NOT be called for codex
        client.create_session.assert_not_called()
        client.send_prompt.assert_not_called()


class TestEnsureHooks:
    def test_installs_hooks_in_global_and_project(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        hook_script = tmp_path / "hook.sh"
        hook_script.write_text("#!/bin/bash\n")

        with patch("wiz.bridge.runner._HOOK_SCRIPT", str(hook_script)), \
             patch("wiz.bridge.runner.Path.home", return_value=tmp_path):
            result = ensure_hooks(cwd=str(project_dir))

        assert result is True
        # Global settings
        global_data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert "Stop" in global_data["hooks"]
        # Project-level settings
        project_data = json.loads((project_dir / ".claude" / "settings.local.json").read_text())
        assert "Stop" in project_data["hooks"]

    def test_preserves_existing_settings(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = settings_dir / "settings.json"
        settings.write_text(json.dumps({"model": "opus", "env": {"FOO": "bar"}}))

        hook_script = tmp_path / "hook.sh"
        hook_script.write_text("#!/bin/bash\n")

        with patch("wiz.bridge.runner._HOOK_SCRIPT", str(hook_script)), \
             patch("wiz.bridge.runner.Path.home", return_value=tmp_path):
            result = ensure_hooks()

        assert result is True
        data = json.loads(settings.read_text())
        assert data["model"] == "opus"
        assert data["env"]["FOO"] == "bar"
        assert "hooks" in data

    def test_idempotent_when_hooks_present(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = settings_dir / "settings.json"

        hook_script = tmp_path / "hook.sh"
        hook_script.write_text("#!/bin/bash\n")

        # Pre-populate with hooks
        initial = {"hooks": {"Stop": [{"matcher": "*", "hooks": [
            {"type": "command", "command": str(hook_script), "timeout": 5}
        ]}]}}
        settings.write_text(json.dumps(initial))

        with patch("wiz.bridge.runner._HOOK_SCRIPT", str(hook_script)), \
             patch("wiz.bridge.runner.Path.home", return_value=tmp_path):
            result = ensure_hooks()

        assert result is True
        data = json.loads(settings.read_text())
        # Stop should still have exactly 1 entry (not duplicated)
        assert len(data["hooks"]["Stop"]) == 1

    def test_returns_false_if_hook_script_missing(self, tmp_path):
        with patch("wiz.bridge.runner._HOOK_SCRIPT", str(tmp_path / "nonexistent.sh")), \
             patch("wiz.bridge.runner.Path.home", return_value=tmp_path):
            result = ensure_hooks()
        assert result is False
