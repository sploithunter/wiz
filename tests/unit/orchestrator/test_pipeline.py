"""Tests for dev cycle pipeline."""

from unittest import mock
from unittest.mock import MagicMock, patch

from wiz.config.schema import DevCycleConfig, GlobalConfig, WizConfig
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.pipeline import DevCyclePipeline


class TestDevCyclePipeline:
    def _make_pipeline(self, repos=None, timeout=3600, phases=None):
        config = WizConfig(
            repos=repos or [
                {"name": "test", "path": "/tmp/test", "github": "u/t", "enabled": True}
            ],
            dev_cycle=DevCycleConfig(
                cycle_timeout=timeout,
                phases=phases or ["bug_hunt", "bug_fix", "review"],
            ),
        )
        notifier = MagicMock(spec=TelegramNotifier)
        return DevCyclePipeline(config, notifier), config

    @patch("wiz.orchestrator.pipeline.BugHunterAgent")
    @patch("wiz.orchestrator.pipeline.SessionRunner")
    @patch("wiz.orchestrator.pipeline.BridgeClient")
    @patch("wiz.orchestrator.pipeline.BridgeEventMonitor")
    def test_phase_ordering(self, mock_monitor, mock_client, mock_runner, mock_hunter):
        pipeline, config = self._make_pipeline()
        mock_hunter_inst = MagicMock()
        mock_hunter_inst.run.return_value = {"bugs_found": 0}
        mock_hunter.return_value = mock_hunter_inst

        with patch("wiz.orchestrator.pipeline.BugFixerAgent") as mock_fixer, \
             patch("wiz.orchestrator.pipeline.ReviewerAgent") as mock_reviewer:
            mock_fixer.return_value = MagicMock(run=MagicMock(return_value={"issues_processed": 0}))
            mock_reviewer.return_value = MagicMock(run=MagicMock(return_value={"reviews": 0}))

            state = pipeline.run_repo(config.repos[0])

        assert len(state.phases) == 3
        assert state.phases[0].phase == "bug_hunt"
        assert state.phases[1].phase == "bug_fix"
        assert state.phases[2].phase == "review"

    @patch("wiz.orchestrator.pipeline.BugHunterAgent")
    @patch("wiz.orchestrator.pipeline.SessionRunner")
    @patch("wiz.orchestrator.pipeline.BridgeClient")
    @patch("wiz.orchestrator.pipeline.BridgeEventMonitor")
    def test_timeout_enforcement(self, mock_monitor, mock_client, mock_runner, mock_hunter):
        pipeline, config = self._make_pipeline(timeout=0)  # Immediate timeout
        state = pipeline.run_repo(config.repos[0])
        assert state.timed_out is True
        assert len(state.phases) == 0

    def test_disabled_repo_skipped(self):
        pipeline, config = self._make_pipeline(repos=[
            {"name": "a", "path": "/tmp/a", "github": "u/a", "enabled": False},
        ])

        with patch.object(pipeline, "run_repo") as mock_run:
            results = pipeline.run_all()

        assert len(results) == 0
        mock_run.assert_not_called()

    @patch("wiz.orchestrator.pipeline.BugHunterAgent")
    @patch("wiz.orchestrator.pipeline.SessionRunner")
    @patch("wiz.orchestrator.pipeline.BridgeClient")
    @patch("wiz.orchestrator.pipeline.BridgeEventMonitor")
    def test_phase_exception_handled(self, mock_monitor, mock_client, mock_runner, mock_hunter):
        pipeline, config = self._make_pipeline(phases=["bug_hunt"])
        mock_hunter.return_value = MagicMock()
        mock_hunter.return_value.run.side_effect = RuntimeError("bridge exploded")

        state = pipeline.run_repo(config.repos[0])
        assert len(state.phases) == 1
        assert state.phases[0].success is False
        assert "bridge exploded" in state.phases[0].data["error"]

    @patch("wiz.orchestrator.pipeline.DistributedLockManager")
    @patch("wiz.orchestrator.pipeline.BugFixerAgent")
    @patch("wiz.orchestrator.pipeline.SessionRunner")
    @patch("wiz.orchestrator.pipeline.BridgeClient")
    @patch("wiz.orchestrator.pipeline.BridgeEventMonitor")
    def test_distributed_lock_created_when_machine_id_set(
        self, mock_monitor, mock_client, mock_runner, mock_fixer, mock_dlock
    ):
        config = WizConfig(
            **{"global": GlobalConfig(machine_id="mac-1")},
            repos=[{"name": "t", "path": "/tmp/t", "github": "u/t", "enabled": True}],
            dev_cycle=DevCycleConfig(phases=["bug_fix"]),
        )
        notifier = MagicMock(spec=TelegramNotifier)
        pipeline = DevCyclePipeline(config, notifier)

        mock_dlock_inst = MagicMock()
        mock_dlock_inst.cleanup_stale.return_value = 0
        mock_dlock.return_value = mock_dlock_inst
        mock_fixer.return_value = MagicMock(run=MagicMock(return_value={"issues_processed": 0}))

        pipeline.run_repo(config.repos[0])
        mock_dlock.assert_called_once_with(mock.ANY, "mac-1")
        mock_dlock_inst.cleanup_stale.assert_called_once()

    @patch("wiz.orchestrator.pipeline.BugFixerAgent")
    @patch("wiz.orchestrator.pipeline.SessionRunner")
    @patch("wiz.orchestrator.pipeline.BridgeClient")
    @patch("wiz.orchestrator.pipeline.BridgeEventMonitor")
    def test_distributed_lock_not_created_when_no_machine_id(
        self, mock_monitor, mock_client, mock_runner, mock_fixer
    ):
        pipeline, config = self._make_pipeline(phases=["bug_fix"])
        mock_fixer.return_value = MagicMock(run=MagicMock(return_value={"issues_processed": 0}))

        with patch("wiz.orchestrator.pipeline.DistributedLockManager") as mock_dlock:
            pipeline.run_repo(config.repos[0])
            mock_dlock.assert_not_called()
