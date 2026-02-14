"""Tests for bug fixer agent."""

from pathlib import Path
from unittest.mock import MagicMock

from wiz.agents.bug_fixer import BugFixerAgent, _extract_priority
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BugFixerConfig
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
        agent.run("/tmp", issues=issues)
        wt.create.assert_called_once_with("fix", 1)
        wt.push.assert_called_once_with("fix", 1)

    def test_successful_fix_updates_labels(self):
        agent, runner, github, wt, locks = self._make_agent()
        runner.run.return_value = SessionResult(success=True, reason="completed")
        issues = [{"number": 1, "title": "[P2] Bug", "body": "details"}]
        agent.run("/tmp", issues=issues)
        github.update_labels.assert_called_once_with(
            1, add=["needs-review"], remove=["needs-fix", "wiz-bug"]
        )

    def test_max_fixes_per_run(self):
        config = BugFixerConfig(max_fixes_per_run=2)
        agent, runner, github, wt, locks = self._make_agent(config)
        runner.run.return_value = SessionResult(success=True, reason="completed")
        issues = [
            {"number": i, "title": f"[P2] Bug {i}", "body": "x"}
            for i in range(5)
        ]
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
        agent.run("/tmp", issues=issues)
        locks.release.assert_called_once_with("issue-1", "bug-fixer")
