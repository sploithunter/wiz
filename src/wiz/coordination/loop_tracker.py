"""Loop tracker: prevents infinite fix-review cycles."""

from __future__ import annotations

import logging

from wiz.coordination.strikes import StrikeTracker

logger = logging.getLogger(__name__)


class LoopTracker:
    """Track fix-review cycles per issue to prevent infinite loops."""

    def __init__(self, strikes: StrikeTracker, max_cycles: int = 3) -> None:
        self.strikes = strikes
        self.max_cycles = max_cycles

    def record_cycle(self, issue_number: int, reason: str) -> int:
        """Record a fix-review cycle. Returns new cycle count."""
        return self.strikes.record_issue_strike(issue_number, reason)

    def is_max_reached(self, issue_number: int) -> bool:
        """Check if max cycles reached for an issue."""
        return self.strikes.is_escalated(issue_number, self.max_cycles)

    def get_cycle_count(self, issue_number: int) -> int:
        """Get current cycle count for an issue."""
        return self.strikes.get_issue_strikes(issue_number)
