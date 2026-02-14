"""Escalation manager: combines strikes with notifications."""

from __future__ import annotations

import logging

from wiz.coordination.strikes import StrikeTracker
from wiz.notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


class EscalationManager:
    """Combines StrikeTracker with TelegramNotifier for escalation."""

    def __init__(
        self,
        strikes: StrikeTracker,
        notifier: TelegramNotifier,
        max_issue_strikes: int = 3,
        max_file_strikes: int = 3,
    ) -> None:
        self.strikes = strikes
        self.notifier = notifier
        self.max_issue_strikes = max_issue_strikes
        self.max_file_strikes = max_file_strikes

    def check_and_escalate(self, issue_number: int, repo: str) -> bool:
        """Check if issue needs escalation and notify if so. Returns True if escalated."""
        if self.strikes.is_escalated(issue_number, self.max_issue_strikes):
            self.notifier.notify_escalation(
                repo,
                f"#{issue_number}",
                f"Reached {self.max_issue_strikes} strikes",
            )
            return True
        return False

    def check_file_pattern(self, repo: str) -> list[str]:
        """Check for files with recurring failures. Returns list of flagged files."""
        flagged = self.strikes.get_flagged_files(self.max_file_strikes)
        if flagged:
            self.notifier.send_message(
                f"*File Pattern Alert* - {repo}\n"
                f"Files with recurring failures:\n"
                + "\n".join(f"- `{f}`" for f in flagged)
            )
        return flagged
