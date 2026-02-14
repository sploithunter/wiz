"""Tests for bug fixer agent."""

from pathlib import Path
from unittest.mock import MagicMock

from wiz.agents.bug_fixer import BugFixerAgent, _extract_priority
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BugFixerConfig
from wiz.coordination.file_lock import FileLockManager
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.strikes import StrikeTracker
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


class TestStagnationPersistence:
    """Regression tests for issue #2: stagnation detection must persist across runs."""

    def _make_agent(self, tmp_path, stagnation_limit=3):
        runner = MagicMock(spec=SessionRunner)
        config = BugFixerConfig(stagnation_limit=stagnation_limit)
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/worktree")
        locks = MagicMock(spec=FileLockManager)
        locks.acquire.return_value = True
        strikes = StrikeTracker(tmp_path / "strikes.json")
        agent = BugFixerAgent(runner, config, github, worktree, locks, strikes)
        return agent, runner, github, strikes

    def test_repeated_failures_escalate_to_stalled(self, tmp_path):
        """Failed fix attempts must accumulate and eventually trigger fix-stalled."""
        agent, runner, github, strikes = self._make_agent(tmp_path, stagnation_limit=3)
        runner.run.return_value = SessionResult(success=False, reason="timeout")
        issue = [{"number": 7, "title": "[P2] stale", "body": "x"}]

        # First two failures: no stall yet
        agent.run("/tmp", issues=issue)
        agent.run("/tmp", issues=issue)
        github.update_labels.assert_not_called()

        # Third failure: should trigger stalled
        result = agent.run("/tmp", issues=issue)
        github.add_comment.assert_called_with(
            7, "Fix stalled: no progress after multiple attempts"
        )
        github.update_labels.assert_called_with(
            7, add=["fix-stalled"], remove=["needs-fix"]
        )
        assert result["results"][0]["stalled"] is True

    def test_stagnation_persists_across_agent_instances(self, tmp_path):
        """Strike state must survive creation of new BugFixerAgent instances."""
        strike_file = tmp_path / "strikes.json"
        config = BugFixerConfig(stagnation_limit=2)
        issue = [{"number": 10, "title": "[P1] bug", "body": "x"}]

        def make_agent():
            runner = MagicMock(spec=SessionRunner)
            runner.run.return_value = SessionResult(success=False, reason="error")
            github = MagicMock(spec=GitHubIssues)
            wt = MagicMock(spec=WorktreeManager)
            wt.create.return_value = Path("/tmp/wt")
            locks = MagicMock(spec=FileLockManager)
            locks.acquire.return_value = True
            strikes = StrikeTracker(strike_file)
            return BugFixerAgent(runner, config, github, wt, locks, strikes), github

        # Run 1 with agent instance A
        agent_a, gh_a = make_agent()
        agent_a.run("/tmp", issues=issue)
        gh_a.update_labels.assert_not_called()

        # Run 2 with new agent instance B (simulates next wiz cycle)
        agent_b, gh_b = make_agent()
        result = agent_b.run("/tmp", issues=issue)
        gh_b.update_labels.assert_called_with(
            10, add=["fix-stalled"], remove=["needs-fix"]
        )
        assert result["results"][0]["stalled"] is True

    def test_already_stalled_issue_skipped(self, tmp_path):
        """Issues that already hit the stagnation limit should be skipped."""
        agent, runner, github, strikes = self._make_agent(tmp_path, stagnation_limit=2)
        runner.run.return_value = SessionResult(success=False, reason="timeout")
        issue = [{"number": 5, "title": "[P2] bug", "body": "x"}]

        # Exhaust the stagnation limit
        agent.run("/tmp", issues=issue)
        agent.run("/tmp", issues=issue)
        github.reset_mock()
        runner.reset_mock()

        # Next attempt should skip without running
        result = agent.run("/tmp", issues=issue)
        runner.run.assert_not_called()
        assert result["results"][0]["skipped"] is True
        assert result["results"][0]["reason"] == "stalled"

    def test_successful_fix_does_not_record_strike(self, tmp_path):
        """A successful fix should not add a strike."""
        agent, runner, github, strikes = self._make_agent(tmp_path, stagnation_limit=4)
        issue = [{"number": 1, "title": "[P2] bug", "body": "x"}]

        # Fail twice
        runner.run.return_value = SessionResult(success=False, reason="timeout")
        agent.run("/tmp", issues=issue)
        agent.run("/tmp", issues=issue)
        assert strikes.get_issue_strikes(1) == 2

        # Succeed - should NOT add a strike
        runner.run.return_value = SessionResult(success=True, reason="completed")
        agent.run("/tmp", issues=issue)
        assert strikes.get_issue_strikes(1) == 2  # Still 2, not 3

        # Fail again - still below limit (2+1=3 < 4)
        runner.run.return_value = SessionResult(success=False, reason="timeout")
        result = agent.run("/tmp", issues=issue)
        assert result["results"][0]["failed"] is True
        assert strikes.get_issue_strikes(1) == 3
