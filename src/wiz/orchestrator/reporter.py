"""Status reporter: generates cycle summaries."""

from __future__ import annotations

import logging

from wiz.memory.session_logger import SessionLogger
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.state import CycleState

logger = logging.getLogger(__name__)


class StatusReporter:
    """Generates summary of cycle results."""

    def __init__(
        self,
        notifier: TelegramNotifier,
        session_logger: SessionLogger | None = None,
    ) -> None:
        self.notifier = notifier
        self.session_logger = session_logger

    def report(self, states: list[CycleState]) -> str:
        """Generate and send a summary report. Returns the summary text."""
        lines = ["*Dev Cycle Summary*\n"]

        total_bugs = 0
        total_fixed = 0
        total_reviews = 0

        for state in states:
            lines.append(state.summary())
            lines.append("")
            total_bugs += state.bugs_found
            total_fixed += state.issues_fixed
            total_reviews += state.reviews_completed

        lines.append(
            f"Totals: {total_bugs} bugs found, {total_fixed} fixed, "
            f"{total_reviews} reviewed"
        )

        summary = "\n".join(lines)

        # Log to session
        if self.session_logger:
            self.session_logger.log(summary)

        # Send notification
        self.notifier.notify_cycle_complete(summary)

        return summary
