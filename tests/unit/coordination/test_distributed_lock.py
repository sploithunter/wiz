"""Tests for distributed issue locking via GitHub labels."""

from unittest.mock import MagicMock

from wiz.coordination.distributed_lock import (
    CLAIM_PREFIX,
    DistributedLockManager,
    _claim_label,
    _get_claim_labels,
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


class TestDistributedLockManager:
    def _make_manager(self, machine_id="mac-1"):
        github = MagicMock(spec=GitHubIssues)
        mgr = DistributedLockManager(github, machine_id, settle_delay=0)
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

        If another machine crashes with a claim label, cleanup_stale()
        should remove it so the issue isn't blocked forever.
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
