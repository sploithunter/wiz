"""Tests for distributed issue locking via GitHub labels."""

import time
from unittest.mock import MagicMock

from wiz.coordination.distributed_lock import (
    CLAIM_COMMENT_PREFIX,
    DistributedLockManager,
    _claim_label,
    _format_claim_comment,
    _get_claim_labels,
    _parse_claim_comment,
)
from wiz.coordination.github_issues import GitHubIssues


class TestHelpers:
    def test_claim_label(self):
        assert _claim_label("mac-1") == "wiz-claimed-by-mac-1"

    def test_get_claim_labels_empty(self):
        issue = {"labels": [{"name": "wiz-bug"}]}
        assert _get_claim_labels(issue) == []

    def test_get_claim_labels_found(self):
        issue = {"labels": [
            {"name": "wiz-bug"},
            {"name": "wiz-claimed-by-mac-1"},
            {"name": "wiz-claimed-by-mac-2"},
        ]}
        assert _get_claim_labels(issue) == [
            "wiz-claimed-by-mac-1",
            "wiz-claimed-by-mac-2",
        ]

    def test_get_claim_labels_no_labels_key(self):
        assert _get_claim_labels({}) == []

    def test_format_claim_comment(self):
        comment = _format_claim_comment("mac-1")
        assert comment.startswith(f"{CLAIM_COMMENT_PREFIX} mac-1 ")
        parts = comment.split()
        assert len(parts) == 3
        ts = int(parts[2])
        assert abs(ts - int(time.time())) < 5

    def test_parse_claim_comment_valid(self):
        result = _parse_claim_comment("wiz-claim: mac-1 1700000000")
        assert result == ("mac-1", 1700000000)

    def test_parse_claim_comment_invalid(self):
        assert _parse_claim_comment("random comment") is None
        assert _parse_claim_comment("wiz-claim:") is None
        assert _parse_claim_comment("wiz-claim: mac-1") is None
        assert _parse_claim_comment("wiz-claim: mac-1 notanumber") is None

    def test_parse_claim_comment_roundtrip(self):
        comment = _format_claim_comment("test-machine")
        result = _parse_claim_comment(comment)
        assert result is not None
        assert result[0] == "test-machine"
        assert abs(result[1] - int(time.time())) < 5


class TestDistributedLockManager:
    def _make_manager(self, machine_id="mac-1", claim_ttl=7200):
        github = MagicMock(spec=GitHubIssues)
        mgr = DistributedLockManager(
            github, machine_id, settle_delay=0, claim_ttl=claim_ttl,
        )
        return mgr, github

    # --- acquire ---

    def test_acquire_sole_claimer(self):
        mgr, github = self._make_manager("mac-1")
        github.update_labels.return_value = True
        github.get_issue.return_value = {
            "number": 1,
            "labels": [{"name": "wiz-claimed-by-mac-1"}],
        }
        assert mgr.acquire(1) is True

    def test_acquire_conflict_lowest_wins(self):
        mgr, github = self._make_manager("alpha")
        github.update_labels.return_value = True
        github.get_issue.return_value = {
            "number": 1,
            "labels": [
                {"name": "wiz-claimed-by-alpha"},
                {"name": "wiz-claimed-by-beta"},
            ],
        }
        assert mgr.acquire(1) is True

    def test_acquire_conflict_higher_loses(self):
        mgr, github = self._make_manager("beta")
        github.update_labels.return_value = True
        github.get_issue.return_value = {
            "number": 1,
            "labels": [
                {"name": "wiz-claimed-by-alpha"},
                {"name": "wiz-claimed-by-beta"},
            ],
        }
        assert mgr.acquire(1) is False
        # Should have removed our label
        github.update_labels.assert_any_call(1, remove=["wiz-claimed-by-beta"])

    def test_acquire_label_add_fails(self):
        mgr, github = self._make_manager()
        github.update_labels.return_value = False
        assert mgr.acquire(1) is False
        github.get_issue.assert_not_called()

    def test_acquire_get_issue_fails_cleanup(self):
        mgr, github = self._make_manager()
        github.update_labels.return_value = True
        github.get_issue.return_value = None
        assert mgr.acquire(1) is False
        # Should attempt cleanup
        github.update_labels.assert_any_call(1, remove=["wiz-claimed-by-mac-1"])

    def test_acquire_label_disappeared(self):
        """Label disappeared between add and re-read — treat as success."""
        mgr, github = self._make_manager()
        github.update_labels.return_value = True
        github.get_issue.return_value = {
            "number": 1,
            "labels": [],  # No claim labels at all
        }
        assert mgr.acquire(1) is True

    # --- release ---

    def test_release(self):
        mgr, github = self._make_manager("mac-1")
        github.update_labels.return_value = True
        assert mgr.release(42) is True
        github.update_labels.assert_called_once_with(42, remove=["wiz-claimed-by-mac-1"])

    def test_release_failure(self):
        mgr, github = self._make_manager()
        github.update_labels.return_value = False
        assert mgr.release(42) is False

    # --- is_claimed ---

    def test_is_claimed_true(self):
        mgr, _ = self._make_manager()
        issue = {"labels": [{"name": "wiz-claimed-by-other"}]}
        assert mgr.is_claimed(issue) is True

    def test_is_claimed_false(self):
        mgr, _ = self._make_manager()
        issue = {"labels": [{"name": "wiz-bug"}]}
        assert mgr.is_claimed(issue) is False

    def test_is_claimed_no_labels(self):
        mgr, _ = self._make_manager()
        assert mgr.is_claimed({}) is False

    # --- cleanup_stale ---

    def test_cleanup_stale_removes_our_labels(self):
        mgr, github = self._make_manager("mac-1")
        github.list_labels.return_value = ["wiz-claimed-by-mac-1"]
        github.list_issues.return_value = [
            {"number": 10},
            {"number": 20},
        ]
        github.update_labels.return_value = True
        count = mgr.cleanup_stale()
        assert count == 2
        github.list_issues.assert_called_once_with(labels=["wiz-claimed-by-mac-1"])

    def test_cleanup_stale_no_issues(self):
        mgr, github = self._make_manager()
        github.list_labels.return_value = ["wiz-claimed-by-mac-1"]
        github.list_issues.return_value = []
        assert mgr.cleanup_stale() == 0

    def test_cleanup_stale_partial_failure(self):
        mgr, github = self._make_manager("mac-1")
        github.list_labels.return_value = ["wiz-claimed-by-mac-1"]
        github.list_issues.return_value = [
            {"number": 10},
            {"number": 20},
        ]
        github.update_labels.side_effect = [True, False]
        assert mgr.cleanup_stale() == 1

    def test_cleanup_stale_removes_foreign_labels(self):
        """Regression: stale foreign claim labels must be cleaned up.

        If another machine crashes with a claim label (and no heartbeat),
        cleanup_stale() should remove it so the issue isn't blocked forever.
        See: https://github.com/.../issues/65
        """
        mgr, github = self._make_manager("live-machine")
        github.list_labels.return_value = [
            "wiz-bug",
            "wiz-claimed-by-live-machine",
            "wiz-claimed-by-dead-machine",
        ]
        # Our own label has one issue, foreign label has another
        def fake_list_issues(labels=None, **kwargs):
            if labels == ["wiz-claimed-by-live-machine"]:
                return [{"number": 10}]
            if labels == ["wiz-claimed-by-dead-machine"]:
                return [{"number": 20}]
            return []

        github.list_issues.side_effect = fake_list_issues
        github.update_labels.return_value = True
        # No heartbeat comments → foreign claim treated as stale
        github.get_comments.return_value = []

        count = mgr.cleanup_stale()
        assert count == 2
        # Verify both our own and foreign labels were removed
        github.update_labels.assert_any_call(10, remove=["wiz-claimed-by-live-machine"])
        github.update_labels.assert_any_call(20, remove=["wiz-claimed-by-dead-machine"])

    def test_cleanup_stale_no_claim_labels_on_repo(self):
        """When no claim labels exist on the repo, cleanup returns 0."""
        mgr, github = self._make_manager("mac-1")
        github.list_labels.return_value = ["wiz-bug", "needs-fix"]
        assert mgr.cleanup_stale() == 0
        github.list_issues.assert_not_called()

    def test_cleanup_stale_list_labels_failure_returns_zero(self):
        """If list_labels fails (returns []), cleanup handles it gracefully."""
        mgr, github = self._make_manager("mac-1")
        github.list_labels.return_value = []
        assert mgr.cleanup_stale() == 0

    # --- acquire heartbeat ---

    def test_acquire_writes_heartbeat_on_success(self):
        """Winning a lock should write a heartbeat comment."""
        mgr, github = self._make_manager("mac-1")
        github.update_labels.return_value = True
        github.get_issue.return_value = {
            "number": 1,
            "labels": [{"name": "wiz-claimed-by-mac-1"}],
        }
        github.add_comment.return_value = True

        assert mgr.acquire(1) is True
        # Verify heartbeat was written
        github.add_comment.assert_called_once()
        comment = github.add_comment.call_args[0][1]
        assert comment.startswith("wiz-claim: mac-1 ")

    def test_acquire_writes_heartbeat_on_conflict_win(self):
        """Winning a conflict should also write a heartbeat."""
        mgr, github = self._make_manager("alpha")
        github.update_labels.return_value = True
        github.get_issue.return_value = {
            "number": 1,
            "labels": [
                {"name": "wiz-claimed-by-alpha"},
                {"name": "wiz-claimed-by-beta"},
            ],
        }
        github.add_comment.return_value = True

        assert mgr.acquire(1) is True
        github.add_comment.assert_called_once()
        comment = github.add_comment.call_args[0][1]
        assert comment.startswith("wiz-claim: alpha ")

    def test_acquire_no_heartbeat_on_loss(self):
        """Losing a lock should NOT write a heartbeat."""
        mgr, github = self._make_manager("beta")
        github.update_labels.return_value = True
        github.get_issue.return_value = {
            "number": 1,
            "labels": [
                {"name": "wiz-claimed-by-alpha"},
                {"name": "wiz-claimed-by-beta"},
            ],
        }
        assert mgr.acquire(1) is False
        github.add_comment.assert_not_called()

    # --- stale detection with heartbeats ---

    def test_cleanup_stale_preserves_active_foreign_claims(self):
        """Active foreign claims with fresh heartbeats must NOT be removed.

        Regression: cleanup must not clear valid in-progress distributed
        locks held by another machine.
        """
        mgr, github = self._make_manager("live-machine")
        github.list_labels.return_value = [
            "wiz-claimed-by-live-machine",
            "wiz-claimed-by-active-machine",
        ]

        def fake_list_issues(labels=None, **kwargs):
            if labels == ["wiz-claimed-by-live-machine"]:
                return [{"number": 10}]
            if labels == ["wiz-claimed-by-active-machine"]:
                return [{"number": 20}]
            return []

        github.list_issues.side_effect = fake_list_issues
        github.update_labels.return_value = True

        # Issue #20 has a FRESH heartbeat (60 seconds ago)
        fresh_ts = int(time.time()) - 60

        def fake_get_comments(issue_number, last_n=10):
            if issue_number == 20:
                return [{"body": f"wiz-claim: active-machine {fresh_ts}"}]
            return []

        github.get_comments.side_effect = fake_get_comments

        count = mgr.cleanup_stale()
        # Only our own label (#10) should be removed
        assert count == 1
        github.update_labels.assert_called_once_with(
            10, remove=["wiz-claimed-by-live-machine"]
        )

    def test_cleanup_stale_removes_expired_foreign_claims(self):
        """Foreign claims with expired heartbeats should be removed."""
        mgr, github = self._make_manager("live-machine", claim_ttl=3600)
        github.list_labels.return_value = ["wiz-claimed-by-dead-machine"]
        github.list_issues.return_value = [{"number": 20}]
        github.update_labels.return_value = True

        # Heartbeat is 2 hours old (TTL is 1 hour)
        old_ts = int(time.time()) - 7200
        github.get_comments.return_value = [
            {"body": f"wiz-claim: dead-machine {old_ts}"}
        ]

        count = mgr.cleanup_stale()
        assert count == 1
        github.update_labels.assert_called_once_with(
            20, remove=["wiz-claimed-by-dead-machine"]
        )

    def test_cleanup_stale_removes_claims_without_heartbeat(self):
        """Foreign claims with no heartbeat comment are treated as stale."""
        mgr, github = self._make_manager("live-machine")
        github.list_labels.return_value = ["wiz-claimed-by-dead-machine"]
        github.list_issues.return_value = [{"number": 20}]
        github.update_labels.return_value = True
        github.get_comments.return_value = []

        count = mgr.cleanup_stale()
        assert count == 1
        github.update_labels.assert_called_once_with(
            20, remove=["wiz-claimed-by-dead-machine"]
        )

    def test_cleanup_mixed_stale_and_active_foreign(self):
        """Mix of stale own, expired foreign, and active foreign claims."""
        mgr, github = self._make_manager("my-machine", claim_ttl=3600)
        github.list_labels.return_value = [
            "wiz-claimed-by-my-machine",
            "wiz-claimed-by-active-peer",
            "wiz-claimed-by-dead-peer",
        ]

        def fake_list_issues(labels=None, **kwargs):
            if labels == ["wiz-claimed-by-my-machine"]:
                return [{"number": 1}]
            if labels == ["wiz-claimed-by-active-peer"]:
                return [{"number": 2}]
            if labels == ["wiz-claimed-by-dead-peer"]:
                return [{"number": 3}]
            return []

        github.list_issues.side_effect = fake_list_issues
        github.update_labels.return_value = True

        fresh_ts = int(time.time()) - 300   # 5 min ago (within TTL)
        old_ts = int(time.time()) - 7200    # 2 hours ago (expired)

        def fake_get_comments(issue_number, last_n=10):
            if issue_number == 2:
                return [{"body": f"wiz-claim: active-peer {fresh_ts}"}]
            if issue_number == 3:
                return [{"body": f"wiz-claim: dead-peer {old_ts}"}]
            return []

        github.get_comments.side_effect = fake_get_comments

        count = mgr.cleanup_stale()
        # #1 (own) and #3 (expired foreign) removed; #2 (active) preserved
        assert count == 2
        github.update_labels.assert_any_call(1, remove=["wiz-claimed-by-my-machine"])
        github.update_labels.assert_any_call(3, remove=["wiz-claimed-by-dead-peer"])
        # Ensure active peer's label was NOT removed
        for call in github.update_labels.call_args_list:
            assert call != ((2,), {"remove": ["wiz-claimed-by-active-peer"]})
