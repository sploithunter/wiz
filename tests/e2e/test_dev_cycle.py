"""E2E test for dev cycle pipeline with mocked bridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiz.bridge.types import SessionResult
from wiz.config.schema import WizConfig
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.pipeline import DevCyclePipeline


@pytest.mark.e2e
class TestDevCycleE2E:
    """Full pipeline test against mocked bridge."""

    def _make_config(self, tmp_path: Path) -> WizConfig:
        return WizConfig(
            repos=[{
                "name": "test-repo",
                "path": str(tmp_path),
                "github": "owner/test-repo",
                "enabled": True,
            }],
        )

    def _mock_runner_result(self) -> SessionResult:
        return SessionResult(
            success=True,
            reason="completed",
            elapsed=5.0,
            events=[],
        )

    @patch("wiz.orchestrator.pipeline.BridgeClient")
    @patch("wiz.orchestrator.pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.pipeline.GitHubIssues")
    @patch("wiz.orchestrator.pipeline.GitHubPRs")
    @patch("wiz.orchestrator.pipeline.WorktreeManager")
    @patch("wiz.orchestrator.pipeline.FileLockManager")
    @patch("wiz.orchestrator.pipeline.StrikeTracker")
    def test_full_dev_cycle(
        self,
        mock_strikes_cls,
        mock_locks_cls,
        mock_worktree_cls,
        mock_prs_cls,
        mock_github_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)
        notifier = TelegramNotifier(bot_token="", chat_id="", enabled=False)

        # Configure mocks
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.create_session.return_value = "sess-1"
        mock_client.send_prompt.return_value = True
        mock_client.get_session.return_value = {"status": "idle"}
        mock_client.delete_session.return_value = True
        mock_client_cls.return_value = mock_client

        mock_monitor = MagicMock()
        mock_monitor.wait_for_stop.return_value = True
        mock_monitor.stop_detected = True
        mock_monitor.events = []
        mock_monitor_cls.return_value = mock_monitor

        mock_github = MagicMock()
        mock_github.list_issues.return_value = []
        mock_github_cls.return_value = mock_github

        mock_prs = MagicMock()
        mock_prs_cls.return_value = mock_prs

        mock_worktree = MagicMock()
        mock_worktree_cls.return_value = mock_worktree

        mock_locks = MagicMock()
        mock_locks_cls.return_value = mock_locks

        mock_strikes = MagicMock()
        mock_strikes.is_escalated.return_value = False
        mock_strikes_cls.return_value = mock_strikes

        pipeline = DevCyclePipeline(config, notifier)
        states = pipeline.run_all()

        assert len(states) == 1
        state = states[0]
        assert state.repo == "test-repo"
        assert len(state.phases) == 3
        assert not state.timed_out

    @patch("wiz.orchestrator.pipeline.BridgeClient")
    @patch("wiz.orchestrator.pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.pipeline.GitHubIssues")
    @patch("wiz.orchestrator.pipeline.GitHubPRs")
    @patch("wiz.orchestrator.pipeline.WorktreeManager")
    @patch("wiz.orchestrator.pipeline.FileLockManager")
    @patch("wiz.orchestrator.pipeline.StrikeTracker")
    def test_disabled_repo_skipped(
        self,
        mock_strikes_cls,
        mock_locks_cls,
        mock_worktree_cls,
        mock_prs_cls,
        mock_github_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = WizConfig(
            repos=[{
                "name": "disabled",
                "path": str(tmp_path),
                "github": "owner/disabled",
                "enabled": False,
            }],
        )
        notifier = TelegramNotifier(bot_token="", chat_id="", enabled=False)
        pipeline = DevCyclePipeline(config, notifier)
        states = pipeline.run_all()
        assert len(states) == 0

    @patch("wiz.orchestrator.pipeline.BridgeClient")
    @patch("wiz.orchestrator.pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.pipeline.GitHubIssues")
    @patch("wiz.orchestrator.pipeline.GitHubPRs")
    @patch("wiz.orchestrator.pipeline.WorktreeManager")
    @patch("wiz.orchestrator.pipeline.FileLockManager")
    @patch("wiz.orchestrator.pipeline.StrikeTracker")
    def test_single_phase(
        self,
        mock_strikes_cls,
        mock_locks_cls,
        mock_worktree_cls,
        mock_prs_cls,
        mock_github_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)
        notifier = TelegramNotifier(bot_token="", chat_id="", enabled=False)

        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.create_session.return_value = "sess-1"
        mock_client.send_prompt.return_value = True
        mock_client.get_session.return_value = {"status": "idle"}
        mock_client.delete_session.return_value = True
        mock_client_cls.return_value = mock_client

        mock_monitor = MagicMock()
        mock_monitor.wait_for_stop.return_value = True
        mock_monitor.stop_detected = True
        mock_monitor.events = []
        mock_monitor_cls.return_value = mock_monitor

        mock_github = MagicMock()
        mock_github.list_issues.return_value = []
        mock_github_cls.return_value = mock_github

        mock_prs = MagicMock()
        mock_prs_cls.return_value = mock_prs

        mock_strikes = MagicMock()
        mock_strikes.is_escalated.return_value = False
        mock_strikes_cls.return_value = mock_strikes

        pipeline = DevCyclePipeline(config, notifier)
        repo_config = config.repos[0]
        state = pipeline.run_repo(repo_config, phases=["bug_hunt"])

        assert len(state.phases) == 1
        assert state.phases[0].phase == "bug_hunt"
