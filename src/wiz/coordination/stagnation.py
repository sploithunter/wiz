"""Stagnation detection.

Direct port of harness-bench ralph_base.py:513-538.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class StagnationDetector:
    """Track consecutive no-change iterations and trigger circuit breaker."""

    def __init__(self, limit: int = 3) -> None:
        self.limit = limit
        self.count = 0

    def check(self, files_changed: bool) -> bool:
        """Check for stagnation.

        Returns True if circuit breaker should trigger (stop).
        """
        if not files_changed:
            self.count += 1
            logger.warning(
                "No changes - stagnation count: %d/%d",
                self.count,
                self.limit,
            )
            if self.count >= self.limit:
                logger.error("CIRCUIT BREAKER: Stopping due to stagnation")
                return True
        else:
            self.count = 0
        return False

    def reset(self) -> None:
        """Reset the stagnation counter."""
        self.count = 0

    @property
    def is_stagnant(self) -> bool:
        return self.count >= self.limit
