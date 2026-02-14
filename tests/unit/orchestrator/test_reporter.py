"""Tests for status reporter."""

from unittest.mock import MagicMock

from wiz.memory.session_logger import SessionLogger
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.reporter import StatusReporter
from wiz.orchestrator.state import CycleState


class TestStatusReporter:
    def test_summary_formatting(self):
        notifier = MagicMock(spec=TelegramNotifier)
        reporter = StatusReporter(notifier)

        state = CycleState(repo="test/repo")
        state.add_phase("bug_hunt", True, {"bugs_found": 3}, 60.0)
        state.add_phase("bug_fix", True, {"issues_processed": 2}, 120.0)
        state.add_phase("review", True, {"reviews": 2}, 30.0)
        state.total_elapsed = 210.0

        summary = reporter.report([state])
        assert "test/repo" in summary
        assert "3 bugs found" in summary
        assert "2 fixed" in summary
        notifier.notify_cycle_complete.assert_called_once()

    def test_multiple_repos(self):
        notifier = MagicMock(spec=TelegramNotifier)
        reporter = StatusReporter(notifier)

        state1 = CycleState(repo="repo1")
        state1.add_phase("bug_hunt", True, {"bugs_found": 1}, 10.0)
        state2 = CycleState(repo="repo2")
        state2.add_phase("bug_hunt", True, {"bugs_found": 2}, 20.0)

        summary = reporter.report([state1, state2])
        assert "repo1" in summary
        assert "repo2" in summary
        assert "3 bugs found" in summary

    def test_with_session_logger(self, tmp_path):
        notifier = MagicMock(spec=TelegramNotifier)
        logger = SessionLogger(tmp_path / "sessions")
        logger.start_session("test")
        reporter = StatusReporter(notifier, logger)

        state = CycleState(repo="test")
        state.total_elapsed = 5.0
        reporter.report([state])

        # Logger should have been written to
        content = logger._current_log.read_text()
        assert "test" in content
