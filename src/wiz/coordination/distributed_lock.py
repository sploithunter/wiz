"""Distributed issue locking via GitHub labels.

Uses wiz-claimed-by-{machine_id} labels as a distributed lock so that
multiple Wiz instances on different machines don't pick up the same issue.

Claim heartbeats are written as issue comments in the format:
    wiz-claim: {machine_id} {unix_timestamp}

This allows cleanup_stale() to distinguish active claims from stale ones
by checking the heartbeat age against the configured claim_ttl.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from wiz.coordination.github_issues import GitHubIssues

logger = logging.getLogger(__name__)

CLAIM_PREFIX = "wiz-claimed-by-"
CLAIM_COMMENT_PREFIX = "wiz-claim:"

# Default claim TTL: 2 hours. Claims older than this are considered stale.
DEFAULT_CLAIM_TTL = 7200


def _claim_label(machine_id: str) -> str:
    return f"{CLAIM_PREFIX}{machine_id}"


def _get_claim_labels(issue: dict[str, Any]) -> list[str]:
    """Extract all wiz-claimed-by-* label names from an issue."""
    return [
        lbl["name"]
        for lbl in issue.get("labels", [])
        if isinstance(lbl, dict) and lbl.get("name", "").startswith(CLAIM_PREFIX)
    ]


def _format_claim_comment(machine_id: str) -> str:
    """Format a claim heartbeat comment for lease tracking."""
    return f"{CLAIM_COMMENT_PREFIX} {machine_id} {int(time.time())}"


def _parse_claim_comment(body: str) -> tuple[str, int] | None:
    """Parse a claim heartbeat comment.

    Returns (machine_id, unix_timestamp) or None if not a valid heartbeat.
    """
    body = body.strip()
    if not body.startswith(CLAIM_COMMENT_PREFIX):
        return None
    parts = body.split()
    if len(parts) < 3:
        return None
    try:
        return (parts[1], int(parts[2]))
    except (ValueError, IndexError):
        return None


class DistributedLockManager:
    """Distributed issue lock using GitHub labels.

    Claim protocol:
    1. Add wiz-claimed-by-{machine_id} label to the issue
    2. Wait settle_delay seconds for concurrent writers
    3. Re-read the issue from GitHub
    4. If multiple claim labels exist, lowest machine_id (lexicographic) wins;
       losers remove their label
    5. Winner writes a heartbeat comment for lease tracking

    Cleanup uses heartbeat timestamps to distinguish stale from active claims.
    Only claims whose heartbeat has expired (or is missing) are removed.
    """

    def __init__(
        self,
        github: GitHubIssues,
        machine_id: str,
        settle_delay: float = 1.0,
        claim_ttl: float = DEFAULT_CLAIM_TTL,
    ) -> None:
        self.github = github
        self.machine_id = machine_id
        self.settle_delay = settle_delay
        self.claim_ttl = claim_ttl
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
            self._write_heartbeat(issue_number)
            return True

        # Multiple claimers: lowest machine_id wins
        claim_ids = sorted(
            lbl.removeprefix(CLAIM_PREFIX) for lbl in claims
        )
        winner = claim_ids[0]

        if winner == self.machine_id:
            logger.info("Won distributed lock for #%d against %s", issue_number, claim_ids[1:])
            self._write_heartbeat(issue_number)
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

    def _write_heartbeat(self, issue_number: int) -> None:
        """Write a claim heartbeat comment for lease tracking."""
        comment = _format_claim_comment(self.machine_id)
        self.github.add_comment(issue_number, comment)

    def _get_claim_age(self, issue_number: int, claim_machine: str) -> int | None:
        """Get the age of a claim's heartbeat in seconds.

        Returns None if no heartbeat comment is found for the given machine.
        """
        try:
            comments = self.github.get_comments(issue_number, last_n=10)
        except Exception:
            logger.debug("Failed to read comments for #%d", issue_number)
            return None

        # Search from most recent to oldest for the matching heartbeat
        for comment in reversed(comments):
            parsed = _parse_claim_comment(comment.get("body", ""))
            if parsed and parsed[0] == claim_machine:
                return int(time.time()) - parsed[1]

        return None

    def _is_claim_stale(self, issue_number: int, label: str) -> bool:
        """Check if a specific claim label is stale (safe to remove).

        Our own claims from a previous run are always stale (we crashed/restarted).
        Foreign claims are checked against their heartbeat timestamp.
        """
        claim_machine = label.removeprefix(CLAIM_PREFIX)

        # Our own claims are always stale at startup
        if claim_machine == self.machine_id:
            return True

        # Foreign claims: check heartbeat age
        age = self._get_claim_age(issue_number, claim_machine)

        if age is None:
            logger.info(
                "No heartbeat for claim %r on #%d — treating as stale",
                label, issue_number,
            )
            return True

        if age > self.claim_ttl:
            logger.info(
                "Claim %r on #%d expired: age=%ds > ttl=%ds",
                label, issue_number, age, self.claim_ttl,
            )
            return True

        logger.info(
            "Claim %r on #%d is active: age=%ds <= ttl=%ds — preserving",
            label, issue_number, age, self.claim_ttl,
        )
        return False

    def cleanup_stale(self) -> int:
        """Remove stale claim labels from open issues (crash recovery).

        Uses heartbeat timestamps to distinguish stale from active claims:
        - Our own claims: always removed (we crashed/restarted)
        - Foreign claims with expired heartbeat: removed
        - Foreign claims with no heartbeat: removed (legacy/missing metadata)
        - Foreign claims with fresh heartbeat: preserved
        """
        all_labels = self.github.list_labels()
        claim_labels = [lbl for lbl in all_labels if lbl.startswith(CLAIM_PREFIX)]

        if not claim_labels:
            return 0

        count = 0
        for label in claim_labels:
            issues = self.github.list_issues(labels=[label])
            for issue in issues:
                number = issue.get("number", 0)
                if not self._is_claim_stale(number, label):
                    continue
                if self.github.update_labels(number, remove=[label]):
                    count += 1
                    if label == self._label:
                        logger.info("Cleaned up own stale claim on #%d", number)
                    else:
                        logger.info(
                            "Cleaned up stale foreign claim %r on #%d",
                            label, number,
                        )
        return count
