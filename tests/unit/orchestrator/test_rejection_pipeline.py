"""Tests for rejection cycle pipeline."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.config.schema import RejectionLearnerConfig, RepoConfig, WizConfig
from wiz.orchestrator.rejection_pipeline import RejectionCyclePipeline


class TestRejectionCyclePipeline:
    def _make_pipeline(self, enabled=True, min_rejections=5):
        config = WizConfig(
            repos=[
                {"name": "wiz", "path": "/tmp/wiz", "github": "u/wiz", "enabled": True}
            ],
            rejection_learner=RejectionLearnerConfig(
                enabled=enabled,
                min_rejections=min_rejections,
                lookback_days=7,
            ),
        )
        return RejectionCyclePipeline(config), config

    def test_disabled_config_skips(self):
        pipeline, _ = self._make_pipeline(enabled=False)
        state = pipeline.run()
        assert len(state.phases) == 1
        assert state.phases[0].data.get("skipped") == "disabled"

    @patch("wiz.orchestrator.rejection_pipeline.RejectionJournal")
    def test_below_threshold_skips(self, mock_journal_cls):
        pipeline, _ = self._make_pipeline(min_rejections=5)
        mock_journal = MagicMock()
        mock_journal.read.return_value = [{"issue": 1}, {"issue": 2}]  # Only 2 < 5
        mock_journal_cls.return_value = mock_journal

        state = pipeline.run()
        assert state.phases[0].data.get("skipped") == "below_threshold"
        assert state.phases[0].data.get("count") == 2

    @patch("wiz.orchestrator.rejection_pipeline.RejectionLearnerAgent")
    @patch("wiz.orchestrator.rejection_pipeline.RejectionJournal")
    @patch("wiz.orchestrator.rejection_pipeline.SessionRunner")
    @patch("wiz.orchestrator.rejection_pipeline.BridgeClient")
    @patch("wiz.orchestrator.rejection_pipeline.BridgeEventMonitor")
    def test_pipeline_runs_agent(
        self, mock_monitor, mock_client, mock_runner, mock_journal_cls, mock_agent_cls
    ):
        pipeline, _ = self._make_pipeline(min_rejections=2)
        mock_journal = MagicMock()
        mock_journal.read.return_value = [
            {"issue": 1}, {"issue": 2}, {"issue": 3},
        ]
        mock_journal_cls.return_value = mock_journal

        mock_agent = MagicMock()
        mock_agent.run.return_value = {"success": True, "patterns_found": 1, "proposals": 1}
        mock_agent_cls.return_value = mock_agent

        state = pipeline.run()
        assert state.phases[0].success is True
        assert state.phases[0].data.get("patterns_found") == 1
        mock_agent.run.assert_called_once()

    def test_no_enabled_repos(self):
        config = WizConfig(
            repos=[
                {"name": "x", "path": "/tmp/x", "github": "u/x", "enabled": False}
            ],
            rejection_learner=RejectionLearnerConfig(enabled=True, min_rejections=0),
        )
        pipeline = RejectionCyclePipeline(config)

        with patch("wiz.orchestrator.rejection_pipeline.RejectionJournal") as mock_journal_cls:
            mock_journal = MagicMock()
            mock_journal.read.return_value = [{"issue": 1}]
            mock_journal_cls.return_value = mock_journal

            state = pipeline.run()
            assert state.phases[0].success is False
            assert state.phases[0].data.get("error") == "no_enabled_repos"
