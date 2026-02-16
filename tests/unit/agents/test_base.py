"""Tests for base agent."""

from typing import Any
from unittest.mock import MagicMock

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult


class ConcreteAgent(BaseAgent):
    agent_type = "claude"
    agent_name = "test-agent"

    def build_prompt(self, **kwargs: Any) -> str:
        return f"Test prompt: {kwargs.get('task', 'default')}"

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        return {"processed": True, "success": result.success}


class TestBaseAgent:
    def test_template_method_calls(self):
        runner = MagicMock(spec=SessionRunner)
        runner.run.return_value = SessionResult(
            success=True, reason="completed", elapsed=5.0
        )

        agent = ConcreteAgent(runner)
        result = agent.run("/tmp", timeout=60, task="find bugs")

        runner.run.assert_called_once_with(
            name="wiz-test-agent",
            cwd="/tmp",
            prompt="Test prompt: find bugs",
            agent="claude",
            timeout=60,
            flags=None,
        )
        assert result["processed"] is True
        assert result["success"] is True

    def test_agent_type_passed_to_runner(self):
        runner = MagicMock(spec=SessionRunner)
        runner.run.return_value = SessionResult(
            success=False, reason="timeout", elapsed=600.0
        )

        agent = ConcreteAgent(runner)
        agent.agent_type = "codex"
        agent.run("/tmp")

        assert runner.run.call_args[1]["agent"] == "codex"

    def test_failed_result_propagated(self):
        runner = MagicMock(spec=SessionRunner)
        runner.run.return_value = SessionResult(
            success=False, reason="bridge_unavailable"
        )

        agent = ConcreteAgent(runner)
        result = agent.run("/tmp")
        assert result["success"] is False


class TestLoadInstructions:
    """Regression tests for #58: agent CLAUDE.md paths must resolve correctly."""

    def test_load_instructions_from_cwd(self, tmp_path):
        """_load_instructions finds CLAUDE.md under cwd/agents/<agent_name>/."""
        agent_dir = tmp_path / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        md_file = agent_dir / "CLAUDE.md"
        md_file.write_text("# Test instructions")

        runner = MagicMock(spec=SessionRunner)
        agent = ConcreteAgent(runner)
        result = agent._load_instructions(str(tmp_path))
        assert result == "# Test instructions"

    def test_load_instructions_returns_empty_when_missing(self, tmp_path):
        """_load_instructions returns empty string when no CLAUDE.md exists."""
        runner = MagicMock(spec=SessionRunner)
        agent = ConcreteAgent(runner)
        result = agent._load_instructions(str(tmp_path))
        assert result == ""

    def test_load_instructions_no_cwd_uses_fallback(self):
        """_load_instructions with no cwd falls back to repo root detection."""
        runner = MagicMock(spec=SessionRunner)
        agent = ConcreteAgent(runner)
        # Should not raise even without cwd
        result = agent._load_instructions(None)
        # test-agent doesn't exist in the real repo, so should return ""
        assert result == ""

    def test_all_agents_use_load_instructions_not_hardcoded_path(self):
        """Verify no agent module defines a CLAUDE_MD_PATH constant (issue #58).

        All agents must use self._load_instructions() from BaseAgent instead
        of hardcoding path resolution with a module-level constant.
        """
        import importlib
        agent_modules = [
            "wiz.agents.bug_fixer",
            "wiz.agents.bug_hunter",
            "wiz.agents.reviewer",
            "wiz.agents.feature_proposer",
            "wiz.agents.blog_writer",
            "wiz.agents.social_manager",
        ]
        for mod_name in agent_modules:
            mod = importlib.import_module(mod_name)
            assert not hasattr(mod, "CLAUDE_MD_PATH"), (
                f"{mod_name} still defines CLAUDE_MD_PATH; "
                f"it should use self._load_instructions() instead"
            )

    def test_feature_proposer_build_prompt_does_not_raise(self):
        """Regression: FeatureProposerAgent.build_prompt must not raise NameError."""
        from wiz.agents.feature_proposer import FeatureProposerAgent
        from wiz.config.schema import FeatureProposerConfig
        from wiz.coordination.github_issues import GitHubIssues
        from wiz.coordination.worktree import WorktreeManager

        runner = MagicMock(spec=SessionRunner)
        config = FeatureProposerConfig()
        github = MagicMock(spec=GitHubIssues)
        worktree = MagicMock(spec=WorktreeManager)
        agent = FeatureProposerAgent(runner, config, github, worktree)

        # This raised NameError before the fix
        prompt = agent.build_prompt(mode="propose", cwd="/tmp")
        assert "Propose Features" in prompt

    def test_social_manager_build_prompt_uses_load_instructions(self, tmp_path):
        """Regression: SocialManagerAgent must load instructions via _load_instructions."""
        from wiz.agents.social_manager import SocialManagerAgent
        from wiz.config.schema import SocialManagerConfig
        from wiz.integrations.typefully import TypefullyClient

        # Create a CLAUDE.md for the social-manager agent
        agent_dir = tmp_path / "agents" / "social-manager"
        agent_dir.mkdir(parents=True)
        (agent_dir / "CLAUDE.md").write_text("# Social instructions")

        runner = MagicMock(spec=SessionRunner)
        config = SocialManagerConfig()
        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = False
        agent = SocialManagerAgent(runner, config, typefully=typefully)

        prompt = agent.build_prompt(cwd=str(tmp_path))
        assert "Social instructions" in prompt
