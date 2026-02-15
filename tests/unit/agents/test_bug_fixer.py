"""Tests for bug fixer agent."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.agents.bug_fixer import BugFixerAgent, _check_files_changed, _extract_priority
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BugFixerConfig
from wiz.coordination.distributed_lock import DistributedLockManager
from wiz.coordination.file_lock import FileLockManager
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.worktree import WorktreeManager


class TestPriorityExtraction:
    def test_p0(self):
        assert _extract_priority({"title": "[P0] Critical bug"}) == 0

    def test_p2(self):
        assert _extract_priority({"title": "[P2] Moderate bug"}) == 2

    def test_no_priority(self):
        assert _extract_priority({"title": "Some bug"}) == 5  # After all priorities


class TestCheckFilesChanged:
    @patch("wiz.agents.bug_fixer.subprocess.run")
    def test_returns_true_when_diff_exists(self, mock_run):
        mock_run.return_value = MagicMock(stdout=" src/foo.py | 3 +++\n 1 file changed")
        assert _check_files_changed("/tmp/wt") is True

    @patch("wiz.agents.bug_fixer.subprocess.run")
    def test_returns_false_when_no_diff(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        assert _check_files_changed("/tmp/wt") is False

    @patch("wiz.agents.bug_fixer.subprocess.run")
    def test_returns_false_on_error(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.CalledProcessError(1, "git")
        assert _check_files_changed("/tmp/wt") is False


class TestBugFixerAgent:
    def _make_agent(self, config=None):
        runner = MagicMock(spec=SessionRunner)
        config = config or BugFixerConfig()
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/worktree")
        locks = MagicMock(spec=FileLockManager)
        locks.acquire.return_value = True
        agent = BugFixerAgent(runner, config, github, worktree, locks)
        return agent, runner, github, worktree, locks

    def test_priority_sorting(self):
        agent, runner, github, wt, locks = self._make_agent()
        runner.run.return_value = SessionResult(success=True, reason="completed")
        github.list_issues.return_value = [
            {"number": 3, "title": "[P3] Low bug"},
            {"number": 1, "title": "[P0] Critical bug"},
            {"number": 2, "title": "[P1] Important bug"},
        ]
        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            agent.run("/tmp", issues=github.list_issues.return_value)
        # Should process P0 first
        calls = runner.run.call_args_list
        assert "wiz-bug-fixer-1" in calls[0][1]["name"]

    def test_lock_skip(self):
        agent, runner, github, wt, locks = self._make_agent()
        locks.acquire.return_value = False
        issues = [{"number": 1, "title": "[P2] Bug"}]
        result = agent.run("/tmp", issues=issues)
        assert result["results"][0]["skipped"] is True
        runner.run.assert_not_called()

    def test_worktree_lifecycle(self):
        agent, runner, github, wt, locks = self._make_agent()
        runner.run.return_value = SessionResult(success=True, reason="completed")
        issues = [{"number": 1, "title": "[P2] Bug", "body": "details"}]
        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            agent.run("/tmp", issues=issues)
        wt.create.assert_called_once_with("fix", 1)
        wt.push.assert_called_once_with("fix", 1)

    def test_successful_fix_updates_labels(self):
        agent, runner, github, wt, locks = self._make_agent()
        runner.run.return_value = SessionResult(success=True, reason="completed")
        issues = [{"number": 1, "title": "[P2] Bug", "body": "details"}]
        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            agent.run("/tmp", issues=issues)
        github.update_labels.assert_called_once_with(
            1, add=["needs-review"], remove=["needs-fix", "wiz-bug"]
        )

    @patch("wiz.agents.bug_fixer._check_files_changed", return_value=False)
    def test_stagnation_detection_with_no_file_changes(self, _mock_check):
        config = BugFixerConfig(stagnation_limit=1)
        agent, runner, github, wt, locks = self._make_agent(config)
        runner.run.return_value = SessionResult(success=True, reason="completed")
        issues = [{"number": 1, "title": "[P2] Bug"}]
        result = agent.run("/tmp", issues=issues)
        assert result["results"][0].get("stalled") is True
        github.update_labels.assert_called_once_with(
            1, add=["fix-stalled"], remove=["needs-fix"]
        )

    def test_max_fixes_per_run(self):
        config = BugFixerConfig(max_fixes_per_run=2)
        agent, runner, github, wt, locks = self._make_agent(config)
        runner.run.return_value = SessionResult(success=True, reason="completed")
        issues = [
            {"number": i, "title": f"[P2] Bug {i}", "body": "x"}
            for i in range(5)
        ]
        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            result = agent.run("/tmp", issues=issues)
        assert result["issues_processed"] == 2
        assert runner.run.call_count == 2

    def test_failed_fix(self):
        agent, runner, github, wt, locks = self._make_agent()
        runner.run.return_value = SessionResult(success=False, reason="timeout")
        issues = [{"number": 1, "title": "[P2] Bug", "body": "x"}]
        result = agent.run("/tmp", issues=issues)
        assert result["results"][0]["failed"] is True
        wt.push.assert_not_called()

    def test_lock_released_after_processing(self):
        agent, runner, github, wt, locks = self._make_agent()
        runner.run.return_value = SessionResult(success=True, reason="completed")
        issues = [{"number": 1, "title": "[P2] Bug"}]
        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            agent.run("/tmp", issues=issues)
        locks.release.assert_called_once_with("issue-1", "bug-fixer")

    def test_distributed_lock_skipped_when_none(self):
        """No distributed_locks param means no distributed locking."""
        agent, runner, github, wt, locks = self._make_agent()
        assert agent.distributed_locks is None
        runner.run.return_value = SessionResult(success=True, reason="completed")
        issues = [{"number": 1, "title": "[P2] Bug"}]
        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            agent.run("/tmp", issues=issues)
        runner.run.assert_called_once()

    def test_distributed_lock_prefilter(self):
        """Issues already claimed by another machine are filtered out."""
        agent, runner, github, wt, locks = self._make_agent()
        dlocks = MagicMock(spec=DistributedLockManager)
        agent.distributed_locks = dlocks
        dlocks.is_claimed.side_effect = lambda i: i.get("number") == 2
        dlocks.acquire.return_value = True
        runner.run.return_value = SessionResult(success=True, reason="completed")

        issues = [
            {"number": 1, "title": "[P2] Bug 1", "labels": []},
            {"number": 2, "title": "[P2] Bug 2", "labels": [{"name": "wiz-claimed-by-other"}]},
        ]
        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            result = agent.run("/tmp", issues=issues)
        # Only issue 1 should be processed
        assert result["issues_processed"] == 1
        dlocks.acquire.assert_called_once_with(1)

    def test_distributed_lock_released_on_success(self):
        agent, runner, github, wt, locks = self._make_agent()
        dlocks = MagicMock(spec=DistributedLockManager)
        agent.distributed_locks = dlocks
        dlocks.is_claimed.return_value = False
        dlocks.acquire.return_value = True
        runner.run.return_value = SessionResult(success=True, reason="completed")

        issues = [{"number": 5, "title": "[P2] Bug"}]
        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            agent.run("/tmp", issues=issues)
        dlocks.release.assert_called_once_with(5)

    def test_distributed_lock_released_on_failure(self):
        agent, runner, github, wt, locks = self._make_agent()
        dlocks = MagicMock(spec=DistributedLockManager)
        agent.distributed_locks = dlocks
        dlocks.is_claimed.return_value = False
        dlocks.acquire.return_value = True
        runner.run.side_effect = RuntimeError("boom")

        issues = [{"number": 5, "title": "[P2] Bug"}]
        try:
            agent.run("/tmp", issues=issues)
        except RuntimeError:
            pass
        dlocks.release.assert_called_once_with(5)
