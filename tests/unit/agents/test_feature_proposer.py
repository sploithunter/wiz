"""Tests for feature proposer agent.

Includes regression test for issue #53: model config passthrough.
"""

from pathlib import Path
from unittest.mock import MagicMock

from wiz.agents.feature_proposer import FeatureProposerAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import FeatureProposerConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.worktree import WorktreeManager
from wiz.notifications.telegram import TelegramNotifier


class TestFeatureProposerAgent:
    def _make_agent(self, config=None, with_notifier=False):
        runner = MagicMock(spec=SessionRunner)
        config = config or FeatureProposerConfig()
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/feature-wt")
        notifier = MagicMock(spec=TelegramNotifier) if with_notifier else None
        return FeatureProposerAgent(runner, config, github, worktree, notifier=notifier), runner, github, worktree, notifier

    def test_disabled_when_zero(self):
        config = FeatureProposerConfig(features_per_run=0)
        agent, runner, _, _, _ = self._make_agent(config)
        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "disabled"
        runner.run.assert_not_called()

    def test_proposal_mode(self):
        agent, runner, github, _, _ = self._make_agent()
        github.list_issues.side_effect = [[], [], []]  # No approved, no candidates, post-propose check
        runner.run.return_value = SessionResult(success=True, reason="completed")

        result = agent.run("/tmp")
        assert result["mode"] == "propose"
        assert runner.run.call_args[1]["name"] == "wiz-feature-propose"

    def test_implementation_mode(self):
        agent, runner, github, worktree, _ = self._make_agent()
        approved_issue = [{"number": 5, "title": "Add caching", "body": "Details"}]
        github.list_issues.side_effect = [approved_issue]
        runner.run.return_value = SessionResult(success=True, reason="completed")

        result = agent.run("/tmp")
        assert result["mode"] == "implement"
        worktree.create.assert_called_once_with("feature", 5)
        worktree.push.assert_called_once()

    def test_implementation_labels_on_success(self):
        agent, runner, github, _, _ = self._make_agent()
        approved_issue = [{"number": 5, "title": "Add caching", "body": "Details"}]
        github.list_issues.side_effect = [approved_issue]
        runner.run.return_value = SessionResult(success=True, reason="completed")

        agent.run("/tmp")
        github.update_labels.assert_called_once_with(
            5, add=["feature-implemented"], remove=["feature-approved"],
        )

    def test_implementation_no_labels_on_failure(self):
        agent, runner, github, _, _ = self._make_agent()
        approved_issue = [{"number": 5, "title": "Add caching", "body": "Details"}]
        github.list_issues.side_effect = [approved_issue]
        runner.run.return_value = SessionResult(success=False, reason="timeout")

        agent.run("/tmp")
        github.update_labels.assert_not_called()

    def test_no_labels_update_when_push_fails(self):
        """Regression test for #32: labels must not update when push fails."""
        agent, runner, github, worktree, _ = self._make_agent()
        approved_issue = [{"number": 5, "title": "Add caching", "body": "Details"}]
        github.list_issues.side_effect = [approved_issue]
        runner.run.return_value = SessionResult(success=True, reason="completed")
        worktree.push.return_value = False

        result = agent.run("/tmp")
        worktree.push.assert_called_once_with("feature", 5)
        github.update_labels.assert_not_called()
        assert result["success"] is False
        assert result["results"][0]["reason"] == "push_failed"

    def test_backlog_not_empty_awaits_approval(self):
        agent, runner, github, _, _ = self._make_agent()
        github.list_issues.side_effect = [
            [],  # No approved
            [{"number": 1, "title": "candidate", "url": "https://github.com/x/1"}],  # Candidates exist
        ]
        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "awaiting_approval"
        assert result["candidates"] == 1
        runner.run.assert_not_called()

    def test_no_auto_propose_no_approved(self):
        config = FeatureProposerConfig(auto_propose_features=False)
        agent, runner, github, _, _ = self._make_agent(config)
        github.list_issues.side_effect = [[], []]  # No approved, no candidates
        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "no_approved_features"


class TestRequireApproval:
    def _make_agent(self, require_approval):
        runner = MagicMock(spec=SessionRunner)
        config = FeatureProposerConfig(require_approval=require_approval)
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/feature-wt")
        notifier = MagicMock(spec=TelegramNotifier)
        return FeatureProposerAgent(runner, config, github, worktree, notifier=notifier), runner, github, worktree, notifier

    def test_require_approval_true_notifies_and_waits(self):
        agent, runner, github, _, notifier = self._make_agent(require_approval=True)
        candidate = [{"number": 7, "title": "Cool feature", "url": "https://github.com/x/7"}]
        github.list_issues.side_effect = [[], candidate]  # No approved, has candidate

        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "awaiting_approval"
        notifier.send_message.assert_called_once()
        assert "#7" in notifier.send_message.call_args[0][0]
        runner.run.assert_not_called()

    def test_require_approval_false_auto_approves_and_implements(self):
        agent, runner, github, worktree, _ = self._make_agent(require_approval=False)
        candidate = [{"number": 7, "title": "Cool feature", "body": "Details", "url": "https://github.com/x/7"}]
        github.list_issues.side_effect = [[], candidate]  # No approved, has candidate
        runner.run.return_value = SessionResult(success=True, reason="completed")

        result = agent.run("/tmp")
        assert result["mode"] == "implement"
        # Should have auto-approved the candidate
        github.update_labels.assert_any_call(
            7, add=["feature-approved"], remove=["feature-candidate"],
        )
        worktree.create.assert_called_once_with("feature", 7)

    def test_require_approval_false_no_labels_when_push_fails(self):
        """Regression test for #32: auto-approved path must not label when push fails."""
        agent, runner, github, worktree, _ = self._make_agent(require_approval=False)
        candidate = [{"number": 7, "title": "Cool feature", "body": "Details", "url": "https://github.com/x/7"}]
        github.list_issues.side_effect = [[], candidate]
        runner.run.return_value = SessionResult(success=True, reason="completed")
        worktree.push.return_value = False

        result = agent.run("/tmp")
        worktree.push.assert_called_once_with("feature", 7)
        # Auto-approve label change should have happened, but NOT feature-implemented
        implemented_calls = [
            c for c in github.update_labels.call_args_list
            if "feature-implemented" in c[1].get("add", [])
        ]
        assert len(implemented_calls) == 0
        assert result["success"] is False
        assert result["results"][0]["reason"] == "push_failed"

    def test_require_approval_false_labels_implemented_on_success(self):
        agent, runner, github, _, _ = self._make_agent(require_approval=False)
        candidate = [{"number": 7, "title": "Cool feature", "body": "Details", "url": "https://github.com/x/7"}]
        github.list_issues.side_effect = [[], candidate]
        runner.run.return_value = SessionResult(success=True, reason="completed")

        agent.run("/tmp")
        # Should label as implemented after success
        label_calls = github.update_labels.call_args_list
        implemented_call = [c for c in label_calls if "feature-implemented" in c[1].get("add", c[0][1] if len(c[0]) > 1 else [])]
        assert len(implemented_call) >= 1


class TestTelegramNotifications:
    def _make_agent(self):
        runner = MagicMock(spec=SessionRunner)
        config = FeatureProposerConfig()
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/feature-wt")
        notifier = MagicMock(spec=TelegramNotifier)
        return FeatureProposerAgent(runner, config, github, worktree, notifier=notifier), runner, github, notifier

    def test_notifies_on_awaiting_approval(self):
        agent, _, github, notifier = self._make_agent()
        candidate = [{"number": 3, "title": "Add API", "url": "https://github.com/x/3"}]
        github.list_issues.side_effect = [[], candidate]

        agent.run("/tmp")
        notifier.send_message.assert_called_once()
        msg = notifier.send_message.call_args[0][0]
        assert "Feature Candidate" in msg
        assert "feature-approved" in msg

    def test_notifies_after_successful_propose(self):
        agent, runner, github, notifier = self._make_agent()
        github.list_issues.side_effect = [
            [],  # No approved
            [],  # No candidates → propose
            [{"number": 10, "title": "New Idea", "url": "https://github.com/x/10"}],  # Post-propose candidates
        ]
        runner.run.return_value = SessionResult(success=True, reason="completed")

        agent.run("/tmp")
        notifier.send_message.assert_called_once()
        msg = notifier.send_message.call_args[0][0]
        assert "#10" in msg

    def test_no_notification_without_notifier(self):
        runner = MagicMock(spec=SessionRunner)
        config = FeatureProposerConfig()
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        agent = FeatureProposerAgent(runner, config, github, worktree, notifier=None)

        candidate = [{"number": 3, "title": "Add API", "url": "https://github.com/x/3"}]
        github.list_issues.side_effect = [[], candidate]

        # Should not raise even without notifier
        result = agent.run("/tmp")
        assert result["reason"] == "awaiting_approval"

    def test_no_notification_on_failed_propose(self):
        agent, runner, github, notifier = self._make_agent()
        github.list_issues.side_effect = [[], [], []]  # No approved, no candidates, post-propose empty
        runner.run.return_value = SessionResult(success=False, reason="timeout")

        agent.run("/tmp")
        notifier.send_message.assert_not_called()


class TestFeatureProposerModelPassthrough:
    """Regression test for issue #53: model config must reach runner.run."""

    def test_model_passed_in_propose_mode(self):
        config = FeatureProposerConfig(model="custom-model")
        runner = MagicMock(spec=SessionRunner)
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/feature-wt")
        agent = FeatureProposerAgent(runner, config, github, worktree)

        github.list_issues.side_effect = [[], [], []]
        runner.run.return_value = SessionResult(success=True, reason="completed")

        agent.run("/tmp")
        assert runner.run.call_args[1]["model"] == "custom-model"

    def test_model_passed_in_implement_mode(self):
        config = FeatureProposerConfig(model="custom-model")
        runner = MagicMock(spec=SessionRunner)
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/feature-wt")
        agent = FeatureProposerAgent(runner, config, github, worktree)

        approved_issue = [{"number": 5, "title": "Add caching", "body": "Details"}]
        github.list_issues.side_effect = [approved_issue]
        runner.run.return_value = SessionResult(success=True, reason="completed")

        agent.run("/tmp")
        assert runner.run.call_args[1]["model"] == "custom-model"
