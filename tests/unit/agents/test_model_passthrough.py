"""Regression tests for issue #84: agent config model passed to runner.

Every agent that calls runner.run() must forward its config.model value.
These tests verify that model= appears in the runner.run() kwargs for
each agent, using a custom model value to confirm it's not just a default.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.agents.bug_hunter import BugHunterAgent
from wiz.agents.bug_fixer import BugFixerAgent
from wiz.agents.reviewer import ReviewerAgent
from wiz.agents.feature_proposer import FeatureProposerAgent
from wiz.agents.blog_writer import BlogWriterAgent
from wiz.agents.social_manager import SocialManagerAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import (
    BugHunterConfig,
    BugFixerConfig,
    ReviewerConfig,
    FeatureProposerConfig,
    BlogWriterConfig,
    SocialManagerConfig,
)
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.github_prs import GitHubPRs
from wiz.coordination.file_lock import FileLockManager
from wiz.coordination.loop_tracker import LoopTracker
from wiz.coordination.worktree import WorktreeManager
from wiz.notifications.telegram import TelegramNotifier


def _mock_runner(success=True):
    runner = MagicMock(spec=SessionRunner)
    runner.run.return_value = SessionResult(
        success=success, reason="ok", elapsed=1.0
    )
    return runner


class TestBugHunterModelPassthrough:
    def test_model_forwarded_to_runner(self):
        """BugHunter uses BaseAgent.run() — model must appear in runner call."""
        runner = _mock_runner()
        config = BugHunterConfig(model="opus")
        github = MagicMock(spec=GitHubIssues)
        github.list_issues.return_value = []

        agent = BugHunterAgent(runner, config, github)
        agent.run("/tmp", timeout=30)

        assert runner.run.call_args[1]["model"] == "opus"


class TestBugFixerModelPassthrough:
    def test_model_forwarded_to_runner(self):
        """BugFixer overrides run() and calls runner.run() directly."""
        runner = _mock_runner()
        config = BugFixerConfig(model="opus")
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/wt")
        locks = MagicMock(spec=FileLockManager)
        locks.acquire.return_value = True

        agent = BugFixerAgent(runner, config, github, worktree, locks)
        issues = [{"number": 1, "title": "[P2] Test bug", "body": "desc"}]

        with patch("wiz.agents.bug_fixer._check_files_changed", return_value=True):
            agent.run("/tmp", issues=issues)

        assert runner.run.call_args[1]["model"] == "opus"


class TestReviewerModelPassthrough:
    def test_model_forwarded_to_runner(self):
        """Reviewer overrides run() and calls runner.run() directly."""
        runner = _mock_runner()
        config = ReviewerConfig(model="opus")
        github = MagicMock(spec=GitHubIssues)
        github.list_issues.return_value = []
        prs = MagicMock(spec=GitHubPRs)
        loop_tracker = MagicMock(spec=LoopTracker)
        loop_tracker.is_max_reached.return_value = False
        notifier = MagicMock(spec=TelegramNotifier)

        agent = ReviewerAgent(
            runner, config, github, prs, loop_tracker, notifier
        )
        issues = [{"number": 1, "title": "[P2] Bug", "body": "x", "labels": []}]
        agent.run("/tmp", issues=issues)

        assert runner.run.call_args[1]["model"] == "opus"


class TestFeatureProposerModelPassthrough:
    def test_model_forwarded_on_implement(self):
        """FeatureProposer passes model when implementing approved features."""
        runner = _mock_runner()
        config = FeatureProposerConfig(model="opus")
        github = MagicMock(spec=GitHubIssues)
        github.list_issues.return_value = [
            {"number": 10, "title": "Feature X", "body": "impl"}
        ]
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/wt")

        agent = FeatureProposerAgent(runner, config, github, worktree)
        agent.run("/tmp")

        assert runner.run.call_args[1]["model"] == "opus"

    def test_model_forwarded_on_propose(self):
        """FeatureProposer passes model when proposing new features."""
        runner = _mock_runner()
        config = FeatureProposerConfig(model="opus", auto_propose_features=True)
        github = MagicMock(spec=GitHubIssues)
        # No approved or candidate features — triggers propose mode
        github.list_issues.return_value = []
        worktree = MagicMock(spec=WorktreeManager)

        agent = FeatureProposerAgent(runner, config, github, worktree)
        agent.run("/tmp")

        assert runner.run.call_args[1]["model"] == "opus"


class TestBlogWriterModelPassthrough:
    def test_model_forwarded_on_propose(self):
        """BlogWriter passes model in propose mode."""
        runner = _mock_runner()
        config = BlogWriterConfig(model="opus", auto_propose_topics=True)

        agent = BlogWriterAgent(runner, config, memory=None)
        agent.run("/tmp")

        assert runner.run.call_args[1]["model"] == "opus"

    def test_model_forwarded_on_write(self):
        """BlogWriter passes model in write mode (pending topic)."""
        runner = _mock_runner()
        config = BlogWriterConfig(model="opus")
        memory = MagicMock()
        memory.retrieve.return_value = [("blog-proposed-topic", "Test topic")]

        agent = BlogWriterAgent(runner, config, memory=memory)
        agent.run("/tmp")

        assert runner.run.call_args[1]["model"] == "opus"


class TestSocialManagerModelPassthrough:
    def test_model_forwarded_to_runner(self):
        """SocialManager overrides run() and calls runner.run() directly."""
        runner = _mock_runner()
        config = SocialManagerConfig(model="opus", social_posts_per_week=1)

        agent = SocialManagerAgent(runner, config)
        agent.run("/tmp")

        assert runner.run.call_args[1]["model"] == "opus"
