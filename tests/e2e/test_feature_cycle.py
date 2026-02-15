"""E2E test for feature cycle pipeline with mocked bridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiz.bridge.types import SessionResult
from wiz.config.schema import WizConfig
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.feature_pipeline import FeatureCyclePipeline


@pytest.mark.e2e
class TestFeatureCycleE2E:
    """Full feature pipeline test against mocked bridge."""

    def _make_config(self, tmp_path: Path) -> WizConfig:
        return WizConfig(
            repos=[{
                "name": "test-repo",
                "path": str(tmp_path),
                "github": "owner/test-repo",
                "enabled": True,
            }],
        )

    @patch("wiz.orchestrator.feature_pipeline.BridgeClient")
    @patch("wiz.orchestrator.feature_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.feature_pipeline.GitHubIssues")
    @patch("wiz.orchestrator.feature_pipeline.WorktreeManager")
    @patch("wiz.orchestrator.feature_pipeline.TelegramNotifier")
    def test_full_feature_cycle_propose(
        self,
        mock_notifier_cls,
        mock_worktree_cls,
        mock_github_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)

        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.create_session.return_value = "sess-1"
        mock_client.send_prompt.return_value = True
        mock_client.get_session.return_value = {"status": "idle"}
        mock_client.delete_session.return_value = True
        mock_client.cleanup_all_sessions.return_value = 0
        mock_client_cls.return_value = mock_client

        mock_monitor = MagicMock()
        mock_monitor.wait_for_stop.return_value = True
        mock_monitor.stop_detected = True
        mock_monitor.events = []
        mock_monitor_cls.return_value = mock_monitor

        mock_github = MagicMock()
        # No approved, no candidates -> propose mode
        mock_github.list_issues.side_effect = [[], [], []]
        mock_github_cls.return_value = mock_github

        mock_worktree = MagicMock()
        mock_worktree.create.return_value = Path("/tmp/feature-wt")
        mock_worktree_cls.return_value = mock_worktree

        mock_notifier = MagicMock()
        mock_notifier_cls.from_config.return_value = mock_notifier

        pipeline = FeatureCyclePipeline(config)
        states = pipeline.run_all()

        assert len(states) == 1
        state = states[0]
        assert state.repo == "test-repo"
        assert len(state.phases) == 1
        assert "feature" in state.phases[0].phase

    @patch("wiz.orchestrator.feature_pipeline.BridgeClient")
    @patch("wiz.orchestrator.feature_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.feature_pipeline.GitHubIssues")
    @patch("wiz.orchestrator.feature_pipeline.WorktreeManager")
    @patch("wiz.orchestrator.feature_pipeline.TelegramNotifier")
    def test_feature_cycle_implement(
        self,
        mock_notifier_cls,
        mock_worktree_cls,
        mock_github_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)

        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.create_session.return_value = "sess-1"
        mock_client.send_prompt.return_value = True
        mock_client.get_session.return_value = {"status": "idle"}
        mock_client.delete_session.return_value = True
        mock_client.list_sessions.return_value = []
        mock_client.cleanup_all_sessions.return_value = 0
        mock_client_cls.return_value = mock_client

        mock_monitor = MagicMock()
        mock_monitor.wait_for_stop.return_value = True
        mock_monitor.stop_detected = True
        mock_monitor.events = []
        mock_monitor_cls.return_value = mock_monitor

        mock_github = MagicMock()
        # Has an approved feature -> implement mode
        mock_github.list_issues.return_value = [
            {"number": 5, "title": "Add caching", "body": "Details"},
        ]
        mock_github_cls.return_value = mock_github

        mock_worktree = MagicMock()
        mock_worktree.create.return_value = Path("/tmp/feature-wt")
        mock_worktree_cls.return_value = mock_worktree

        mock_notifier = MagicMock()
        mock_notifier_cls.from_config.return_value = mock_notifier

        pipeline = FeatureCyclePipeline(config)
        states = pipeline.run_all()

        assert len(states) == 1
        state = states[0]
        assert len(state.phases) == 1
        assert state.phases[0].phase == "feature_implement"
        mock_worktree.create.assert_called_once_with("feature", 5)
        mock_worktree.push.assert_called_once()

    @patch("wiz.orchestrator.feature_pipeline.BridgeClient")
    @patch("wiz.orchestrator.feature_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.feature_pipeline.GitHubIssues")
    @patch("wiz.orchestrator.feature_pipeline.WorktreeManager")
    @patch("wiz.orchestrator.feature_pipeline.TelegramNotifier")
    def test_disabled_repo_skipped(
        self,
        mock_notifier_cls,
        mock_worktree_cls,
        mock_github_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = WizConfig(
            repos=[{
                "name": "disabled-repo",
                "path": str(tmp_path),
                "github": "owner/disabled-repo",
                "enabled": False,
            }],
        )

        pipeline = FeatureCyclePipeline(config)
        states = pipeline.run_all()
        assert len(states) == 0

    @patch("wiz.orchestrator.feature_pipeline.BridgeClient")
    @patch("wiz.orchestrator.feature_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.feature_pipeline.GitHubIssues")
    @patch("wiz.orchestrator.feature_pipeline.WorktreeManager")
    @patch("wiz.orchestrator.feature_pipeline.TelegramNotifier")
    def test_feature_cycle_awaiting_approval(
        self,
        mock_notifier_cls,
        mock_worktree_cls,
        mock_github_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)

        mock_github = MagicMock()
        # No approved features, has a candidate
        mock_github.list_issues.side_effect = [
            [],  # No approved
            [{"number": 3, "title": "Feature X", "url": "https://github.com/x/3"}],
        ]
        mock_github_cls.return_value = mock_github

        mock_worktree = MagicMock()
        mock_worktree_cls.return_value = mock_worktree

        mock_notifier = MagicMock()
        mock_notifier_cls.from_config.return_value = mock_notifier

        pipeline = FeatureCyclePipeline(config)
        states = pipeline.run_all()

        assert len(states) == 1
        state = states[0]
        # Should be skipped (awaiting approval), but still recorded as a phase
        assert len(state.phases) == 1

    @patch("wiz.orchestrator.feature_pipeline.BridgeClient")
    @patch("wiz.orchestrator.feature_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.feature_pipeline.GitHubIssues")
    @patch("wiz.orchestrator.feature_pipeline.WorktreeManager")
    @patch("wiz.orchestrator.feature_pipeline.TelegramNotifier")
    def test_feature_cycle_error_handling(
        self,
        mock_notifier_cls,
        mock_worktree_cls,
        mock_github_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)

        mock_github = MagicMock()
        mock_github.list_issues.side_effect = RuntimeError("API failure")
        mock_github_cls.return_value = mock_github

        mock_worktree = MagicMock()
        mock_worktree_cls.return_value = mock_worktree

        mock_notifier = MagicMock()
        mock_notifier_cls.from_config.return_value = mock_notifier

        pipeline = FeatureCyclePipeline(config)
        states = pipeline.run_all()

        assert len(states) == 1
        state = states[0]
        assert len(state.phases) == 1
        assert state.phases[0].success is False
        assert "error" in state.phases[0].data
