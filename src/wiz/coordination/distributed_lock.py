"""Distributed issue locking via GitHub labels.

Uses wiz-claimed-by-{machine_id} labels as a distributed lock so that
multiple Wiz instances on different machines don't pick up the same issue.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from wiz.coordination.github_issues import GitHubIssues

logger = logging.getLogger(__name__)

CLAIM_PREFIX = "wiz-claimed-by-"


def _claim_label(machine_id: str) -> str:
    return f"{CLAIM_PREFIX}{machine_id}"


def _get_claim_labels(issue: dict[str, Any]) -> list[str]:
    """Extract all wiz-claimed-by-* label names from an issue."""
    return [
        lbl["name"]
        for lbl in issue.get("labels", [])
        if isinstance(lbl, dict) and lbl.get("name", "").startswith(CLAIM_PREFIX)
    ]


class DistributedLockManager:
    """Distributed issue lock using GitHub labels.

    Claim protocol:
    1. Add wiz-claimed-by-{machine_id} label to the issue
    2. Wait settle_delay seconds for concurrent writers
    3. Re-read the issue from GitHub
    4. If multiple claim labels exist, lowest machine_id (lexicographic) wins;
       losers remove their label
    """

    def __init__(
        self,
        github: GitHubIssues,
        machine_id: str,
        settle_delay: float = 1.0,
    ) -> None:
        self.github = github
        self.machine_id = machine_id
        self.settle_delay = settle_delay
        self._label = _claim_label(machine_id)

    def acquire(self, issue_number: int) -> bool:
        """Try to claim an issue. Returns True if we won the lock."""
        # Step 1: add our claim label
        ok = self.github.update_labels(issue_number, add=[self._label])
        if not ok:
            logger.warning("Failed to add claim label to #%d", issue_number)
            return False

        # Step 2: settle
        if self.settle_delay > 0:
            time.sleep(self.settle_delay)

        # Step 3: re-read issue
        issue = self.github.get_issue(issue_number)
        if issue is None:
            # Can't verify — be safe, clean up and bail
            logger.warning("Failed to re-read #%d after claiming, releasing", issue_number)
            self.github.update_labels(issue_number, remove=[self._label])
            return False

        # Step 4: resolve conflicts
        claims = _get_claim_labels(issue)
        if len(claims) <= 1:
            # We're the only claimer (or label disappeared — treat as ours)
            return True

        # Multiple claimers: lowest machine_id wins
        claim_ids = sorted(
            lbl.removeprefix(CLAIM_PREFIX) for lbl in claims
        )
        winner = claim_ids[0]

        if winner == self.machine_id:
            logger.info("Won distributed lock for #%d against %s", issue_number, claim_ids[1:])
            return True

        # We lost — remove our label
        logger.info(
            "Lost distributed lock for #%d to %s, releasing", issue_number, winner
        )
        self.github.update_labels(issue_number, remove=[self._label])
        return False

    def release(self, issue_number: int) -> bool:
        """Release our claim on an issue."""
        return self.github.update_labels(issue_number, remove=[self._label])

    def is_claimed(self, issue: dict[str, Any]) -> bool:
        """Check if an issue already has any claim label (pre-filter)."""
        return len(_get_claim_labels(issue)) > 0

    def cleanup_stale(self) -> int:
        """Remove stale claim labels from open issues (crash recovery).

        Removes both our own claims and foreign claims from other machines
        that may have crashed. This prevents stale foreign labels from
        blocking issue processing indefinitely.
        """
        # Discover all wiz-claimed-by-* labels on the repo
        all_labels = self.github.list_labels()
        claim_labels = [lbl for lbl in all_labels if lbl.startswith(CLAIM_PREFIX)]

        if not claim_labels:
            return 0

        count = 0
        for label in claim_labels:
            issues = self.github.list_issues(labels=[label])
            for issue in issues:
                number = issue.get("number", 0)
                if self.github.update_labels(number, remove=[label]):
                    count += 1
                    if label == self._label:
                        logger.info("Cleaned up own stale claim on #%d", number)
                    else:
                        logger.info(
                            "Cleaned up foreign stale claim %r on #%d",
                            label, number,
                        )
        return count
