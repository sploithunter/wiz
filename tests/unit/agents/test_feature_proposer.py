"""Tests for feature proposer agent."""

from pathlib import Path
from unittest.mock import MagicMock

from wiz.agents.feature_proposer import FeatureProposerAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import FeatureProposerConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.worktree import WorktreeManager


class TestFeatureProposerAgent:
    def _make_agent(self, config=None):
        runner = MagicMock(spec=SessionRunner)
        config = config or FeatureProposerConfig()
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        worktree.create.return_value = Path("/tmp/feature-wt")
        return FeatureProposerAgent(runner, config, github, worktree), runner, github, worktree

    def test_disabled_when_zero(self):
        config = FeatureProposerConfig(features_per_run=0)
        agent, runner, _, _ = self._make_agent(config)
        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "disabled"
        runner.run.assert_not_called()

    def test_proposal_mode(self):
        agent, runner, github, _ = self._make_agent()
        github.list_issues.side_effect = [[], []]  # No approved, no candidates
        runner.run.return_value = SessionResult(success=True, reason="completed")

        result = agent.run("/tmp")
        assert result["mode"] == "propose"
        assert runner.run.call_args[1]["name"] == "wiz-feature-propose"

    def test_implementation_mode(self):
        agent, runner, github, worktree = self._make_agent()
        approved_issue = [{"number": 5, "title": "Add caching", "body": "Details"}]
        github.list_issues.side_effect = [approved_issue]
        runner.run.return_value = SessionResult(success=True, reason="completed")

        result = agent.run("/tmp")
        assert result["mode"] == "implement"
        worktree.create.assert_called_once_with("feature", 5)
        worktree.push.assert_called_once()

    def test_backlog_not_empty_skips(self):
        agent, runner, github, _ = self._make_agent()
        github.list_issues.side_effect = [
            [],  # No approved
            [{"number": 1, "title": "candidate"}],  # Backlog not empty
        ]
        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "backlog_not_empty"
        runner.run.assert_not_called()

    def test_no_auto_propose_no_approved(self):
        config = FeatureProposerConfig(auto_propose_features=False)
        agent, runner, github, _ = self._make_agent(config)
        github.list_issues.return_value = []
        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "no_approved_features"
