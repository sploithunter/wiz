"""Tests for base agent."""

from typing import Any
from unittest.mock import MagicMock

import pytest

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


def _make_agent(agent_name, tmp_path):
    """Instantiate the named agent with minimal mocked dependencies."""
    runner = MagicMock(spec=SessionRunner)

    if agent_name == "bug-fixer":
        from wiz.agents.bug_fixer import BugFixerAgent
        from wiz.config.schema import BugFixerConfig
        from wiz.coordination.github_issues import GitHubIssues
        from wiz.coordination.worktree import WorktreeManager
        from wiz.coordination.file_lock import FileLockManager

        return BugFixerAgent(
            runner,
            BugFixerConfig(),
            MagicMock(spec=GitHubIssues),
            MagicMock(spec=WorktreeManager),
            MagicMock(spec=FileLockManager),
        )

    if agent_name == "bug-hunter":
        from wiz.agents.bug_hunter import BugHunterAgent
        from wiz.config.schema import BugHunterConfig
        from wiz.coordination.github_issues import GitHubIssues

        return BugHunterAgent(
            runner, BugHunterConfig(), MagicMock(spec=GitHubIssues)
        )

    if agent_name == "reviewer":
        from wiz.agents.reviewer import ReviewerAgent
        from wiz.config.schema import ReviewerConfig
        from wiz.coordination.github_issues import GitHubIssues
        from wiz.coordination.github_prs import GitHubPRs
        from wiz.coordination.loop_tracker import LoopTracker
        from wiz.notifications.telegram import TelegramNotifier

        return ReviewerAgent(
            runner,
            ReviewerConfig(),
            MagicMock(spec=GitHubIssues),
            MagicMock(spec=GitHubPRs),
            MagicMock(spec=LoopTracker),
            MagicMock(spec=TelegramNotifier),
        )

    if agent_name == "feature-proposer":
        from wiz.agents.feature_proposer import FeatureProposerAgent
        from wiz.config.schema import FeatureProposerConfig
        from wiz.coordination.github_issues import GitHubIssues
        from wiz.coordination.worktree import WorktreeManager

        return FeatureProposerAgent(
            runner,
            FeatureProposerConfig(),
            MagicMock(spec=GitHubIssues),
            MagicMock(spec=WorktreeManager),
        )

    if agent_name == "blog-writer":
        from wiz.agents.blog_writer import BlogWriterAgent
        from wiz.config.schema import BlogWriterConfig

        return BlogWriterAgent(runner, BlogWriterConfig())

    if agent_name == "social-manager":
        from wiz.agents.social_manager import SocialManagerAgent
        from wiz.config.schema import SocialManagerConfig
        from wiz.integrations.typefully import TypefullyClient

        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = False
        return SocialManagerAgent(runner, SocialManagerConfig(), typefully=typefully)

    raise ValueError(f"Unknown agent: {agent_name}")


def _build_prompt_kwargs(agent_name):
    """Return minimal kwargs for build_prompt() for each agent type."""
    if agent_name == "bug-fixer":
        return {"issue": {"title": "Test", "body": "desc", "number": 1}}
    if agent_name == "bug-hunter":
        return {}
    if agent_name == "reviewer":
        return {"issue": {"title": "Test", "body": "desc", "number": 1}}
    if agent_name == "feature-proposer":
        return {"mode": "propose"}
    if agent_name == "blog-writer":
        return {"mode": "propose"}
    if agent_name == "social-manager":
        return {}
    return {}


ALL_AGENT_NAMES = [
    "bug-fixer",
    "bug-hunter",
    "reviewer",
    "feature-proposer",
    "blog-writer",
    "social-manager",
]


class TestBuildPromptIncludesCLAUDEMD:
    """Regression tests for #58: every agent's build_prompt must include CLAUDE.md content."""

    @pytest.mark.parametrize("agent_name", ALL_AGENT_NAMES)
    def test_build_prompt_includes_claude_md_content(self, tmp_path, agent_name):
        """build_prompt() must include the content of agents/<name>/CLAUDE.md.

        Creates a temporary CLAUDE.md with a unique marker string, calls
        build_prompt(cwd=tmp_path), and asserts the marker appears in
        the returned prompt.  This is the core regression test for #58:
        if the path resolution regresses, the marker will be missing.
        """
        marker = f"UNIQUE_MARKER_FOR_{agent_name.upper().replace('-', '_')}"
        agent_dir = tmp_path / "agents" / agent_name
        agent_dir.mkdir(parents=True)
        (agent_dir / "CLAUDE.md").write_text(f"# Instructions\n{marker}")

        agent = _make_agent(agent_name, tmp_path)
        kwargs = _build_prompt_kwargs(agent_name)
        prompt = agent.build_prompt(cwd=str(tmp_path), **kwargs)

        assert marker in prompt, (
            f"{agent_name}: build_prompt() did not include CLAUDE.md content. "
            f"Path resolution may have regressed to the old src/agents/ layout."
        )

    @pytest.mark.parametrize("agent_name", ALL_AGENT_NAMES)
    def test_build_prompt_works_without_claude_md(self, tmp_path, agent_name):
        """build_prompt() must not fail when CLAUDE.md is absent."""
        agent = _make_agent(agent_name, tmp_path)
        kwargs = _build_prompt_kwargs(agent_name)
        # No CLAUDE.md under tmp_path — should still produce a valid prompt
        prompt = agent.build_prompt(cwd=str(tmp_path), **kwargs)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    @pytest.mark.parametrize("agent_name", ALL_AGENT_NAMES)
    def test_path_resolves_under_repo_root_not_src(self, agent_name):
        """Verify the resolved CLAUDE.md path uses agents/ at repo root, not src/agents/.

        The original bug had paths like src/agents/<agent>/CLAUDE.md.
        This test ensures _load_instructions checks the correct location.
        """
        import inspect
        agent = _make_agent(agent_name, None)
        source = inspect.getsource(type(agent).build_prompt)
        assert "src/agents" not in source, (
            f"{agent_name}: build_prompt source still references 'src/agents'. "
            f"Must use self._load_instructions() which resolves from repo root."
        )
