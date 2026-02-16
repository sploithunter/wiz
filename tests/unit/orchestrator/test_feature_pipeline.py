"""Tests for feature cycle pipeline worktree cleanup."""

from unittest.mock import MagicMock, patch

from wiz.config.schema import RepoConfig, WorktreeConfig, WizConfig
from wiz.orchestrator.feature_pipeline import FeatureCyclePipeline


class TestFeatureCyclePipelineCleanup:
    @patch("wiz.orchestrator.feature_pipeline.WorktreeManager")
    @patch("wiz.orchestrator.feature_pipeline.FeatureProposerAgent")
    @patch("wiz.orchestrator.feature_pipeline.SessionRunner")
    @patch("wiz.orchestrator.feature_pipeline.BridgeClient")
    @patch("wiz.orchestrator.feature_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.feature_pipeline.TelegramNotifier")
    def test_worktree_cleanup_called(
        self, mock_notifier_cls, mock_monitor, mock_client, mock_runner,
        mock_proposer, mock_wt_cls,
    ):
        """Regression test for #36: worktree cleanup must be invoked in feature pipeline."""
        config = WizConfig(
            repos=[RepoConfig(name="demo", path="/tmp/demo", github="owner/repo")],
            worktrees=WorktreeConfig(stale_days=5, auto_cleanup_merged=True),
        )
        pipeline = FeatureCyclePipeline(config)

        mock_wt = MagicMock()
        mock_wt.cleanup_stale.return_value = 0
        mock_wt.cleanup_merged.return_value = 0
        mock_wt_cls.return_value = mock_wt
        mock_proposer.return_value = MagicMock(
            run=MagicMock(return_value={"mode": "propose", "success": True}),
        )

        pipeline.run_repo(config.repos[0])

        mock_wt.cleanup_stale.assert_called_once_with(stale_days=5)
        mock_wt.cleanup_merged.assert_called_once()

    @patch("wiz.orchestrator.feature_pipeline.WorktreeManager")
    @patch("wiz.orchestrator.feature_pipeline.FeatureProposerAgent")
    @patch("wiz.orchestrator.feature_pipeline.SessionRunner")
    @patch("wiz.orchestrator.feature_pipeline.BridgeClient")
    @patch("wiz.orchestrator.feature_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.feature_pipeline.TelegramNotifier")
    def test_worktree_cleanup_merged_skipped_when_disabled(
        self, mock_notifier_cls, mock_monitor, mock_client, mock_runner,
        mock_proposer, mock_wt_cls,
    ):
        """Regression test for #36: cleanup_merged not called when disabled."""
        config = WizConfig(
            repos=[RepoConfig(name="demo", path="/tmp/demo", github="owner/repo")],
            worktrees=WorktreeConfig(stale_days=7, auto_cleanup_merged=False),
        )
        pipeline = FeatureCyclePipeline(config)

        mock_wt = MagicMock()
        mock_wt.cleanup_stale.return_value = 0
        mock_wt_cls.return_value = mock_wt
        mock_proposer.return_value = MagicMock(
            run=MagicMock(return_value={"mode": "propose", "success": True}),
        )

        pipeline.run_repo(config.repos[0])

        mock_wt.cleanup_stale.assert_called_once_with(stale_days=7)
        mock_wt.cleanup_merged.assert_not_called()
