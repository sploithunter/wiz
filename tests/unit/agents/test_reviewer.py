"""Tests for reviewer agent."""

from pathlib import Path
from unittest.mock import MagicMock

from wiz.agents.reviewer import ReviewerAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import ReviewerConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.github_prs import GitHubPRs
from wiz.coordination.loop_tracker import LoopTracker
from wiz.coordination.strikes import StrikeTracker
from wiz.notifications.telegram import TelegramNotifier


class TestReviewerAgent:
    def _make_agent(self, tmp_path: Path, config: ReviewerConfig | None = None):
        runner = MagicMock(spec=SessionRunner)
        config = config or ReviewerConfig()
        github = MagicMock(spec=GitHubIssues)
        prs = MagicMock(spec=GitHubPRs)
        strikes = StrikeTracker(tmp_path / "strikes.json")
        loop_tracker = LoopTracker(strikes, max_cycles=config.max_review_cycles)
        notifier = MagicMock(spec=TelegramNotifier)
        return ReviewerAgent(
            runner, config, github, prs, loop_tracker, notifier, repo_name="test/repo"
        ), runner, github, prs, notifier

    def test_approval_path(self, tmp_path: Path):
        """Approved fix -> PR created, issue closed."""
        agent, runner, github, prs, notifier = self._make_agent(tmp_path)
        # Return result with APPROVED in events
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"type": "stop", "response": "APPROVED"}}],
        )
        prs.create_pr.return_value = "https://github.com/test/repo/pull/1"

        issues = [{"number": 1, "title": "[P2] Bug", "body": "details"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "approved"
        prs.create_pr.assert_called_once()
        github.close_issue.assert_called_once_with(1)

    def test_rejection_path(self, tmp_path: Path):
        """Rejected fix -> labels updated, comment added."""
        agent, runner, github, prs, notifier = self._make_agent(tmp_path)
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"type": "stop", "response": "REJECTED: needs work"}}],
        )

        issues = [{"number": 1, "title": "[P2] Bug", "body": "details"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "rejected"
        github.update_labels.assert_called_once_with(
            1, add=["needs-fix"], remove=["needs-review"]
        )
        github.add_comment.assert_called_once()

    def test_escalation_path(self, tmp_path: Path):
        """After max cycles -> escalated to human, Telegram fired."""
        config = ReviewerConfig(max_review_cycles=2)
        agent, runner, github, prs, notifier = self._make_agent(tmp_path, config)

        # Pre-record strikes to bring to threshold
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"type": "stop", "response": "REJECTED"}}],
        )

        issues = [{"number": 1, "title": "[P2] Bug", "body": "x"}]

        # First rejection
        agent.run("/tmp", issues=issues)
        # Second rejection -> escalation
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "escalated"
        notifier.notify_escalation.assert_called()
        # Verify escalation labels
        label_calls = github.update_labels.call_args_list
        last_call = label_calls[-1]
        add_labels = last_call[1].get(
            "add", last_call[0][1] if len(last_call[0]) > 1 else [],
        )
        assert "escalated-to-human" in add_labels

    def test_already_escalated_skips_review(self, tmp_path: Path):
        """If max cycles already reached, skip review entirely."""
        config = ReviewerConfig(max_review_cycles=1)
        agent, runner, github, prs, notifier = self._make_agent(tmp_path, config)

        # Pre-fill strikes
        agent.loop_tracker.record_cycle(1, "prior rejection")

        issues = [{"number": 1, "title": "[P2] Bug"}]
        result = agent.run("/tmp", issues=issues)

        assert result["results"][0]["action"] == "escalated"
        runner.run.assert_not_called()  # No review session needed

    def test_max_reviews_per_run(self, tmp_path: Path):
        config = ReviewerConfig(max_reviews_per_run=2)
        agent, runner, github, prs, notifier = self._make_agent(tmp_path, config)
        runner.run.return_value = SessionResult(
            success=True, reason="completed", events=[]
        )
        prs.create_pr.return_value = "url"

        issues = [
            {"number": i, "title": f"Bug {i}", "body": "x"}
            for i in range(5)
        ]
        result = agent.run("/tmp", issues=issues)
        assert result["reviews"] == 2
