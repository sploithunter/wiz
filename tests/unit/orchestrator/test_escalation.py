"""Tests for escalation manager."""

from pathlib import Path
from unittest.mock import MagicMock

from wiz.coordination.strikes import StrikeTracker
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.escalation import EscalationManager


class TestEscalationManager:
    def test_escalation_trigger(self, tmp_path: Path):
        strikes = StrikeTracker(tmp_path / "strikes.json")
        notifier = MagicMock(spec=TelegramNotifier)
        mgr = EscalationManager(strikes, notifier, max_issue_strikes=2)

        strikes.record_issue_strike(1, "a")
        strikes.record_issue_strike(1, "b")

        assert mgr.check_and_escalate(1, "test/repo") is True
        notifier.notify_escalation.assert_called_once()

    def test_no_escalation_below_threshold(self, tmp_path: Path):
        strikes = StrikeTracker(tmp_path / "strikes.json")
        notifier = MagicMock(spec=TelegramNotifier)
        mgr = EscalationManager(strikes, notifier, max_issue_strikes=3)

        strikes.record_issue_strike(1, "a")
        assert mgr.check_and_escalate(1, "test/repo") is False
        notifier.notify_escalation.assert_not_called()

    def test_file_pattern_detection(self, tmp_path: Path):
        strikes = StrikeTracker(tmp_path / "strikes.json")
        notifier = MagicMock(spec=TelegramNotifier)
        mgr = EscalationManager(strikes, notifier, max_file_strikes=2)

        strikes.record_file_failure("src/bad.py", 1)
        strikes.record_file_failure("src/bad.py", 2)

        flagged = mgr.check_file_pattern("test/repo")
        assert "src/bad.py" in flagged
        notifier.send_message.assert_called_once()

    def test_no_flagged_files(self, tmp_path: Path):
        strikes = StrikeTracker(tmp_path / "strikes.json")
        notifier = MagicMock(spec=TelegramNotifier)
        mgr = EscalationManager(strikes, notifier)

        flagged = mgr.check_file_pattern("test/repo")
        assert flagged == []
        notifier.send_message.assert_not_called()
