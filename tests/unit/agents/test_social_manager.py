"""Tests for social manager agent."""

from unittest.mock import MagicMock

from wiz.agents.social_manager import SocialManagerAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import SocialManagerConfig
from wiz.memory.long_term import LongTermMemory


class TestSocialManagerAgent:
    def _make_agent(self, config=None, with_memory=False):
        runner = MagicMock(spec=SessionRunner)
        config = config or SocialManagerConfig()
        memory = MagicMock(spec=LongTermMemory) if with_memory else None
        if memory:
            memory.retrieve.return_value = []
        return SocialManagerAgent(runner, config, memory), runner, memory

    def test_disabled_mode(self):
        config = SocialManagerConfig(social_posts_per_week=0)
        agent, runner, _ = self._make_agent(config)
        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "disabled"
        runner.run.assert_not_called()

    def test_prompt_construction(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt()
        assert "Typefully" in prompt
        assert "x" in prompt  # Platform

    def test_prompt_with_memory(self):
        agent, _, memory = self._make_agent(with_memory=True)
        memory.retrieve.return_value = [("social", "Recent post about X")]
        prompt = agent.build_prompt()
        assert "Recent Posts" in prompt

    def test_empty_prompt_when_disabled(self):
        config = SocialManagerConfig(social_posts_per_week=0)
        agent, _, _ = self._make_agent(config)
        prompt = agent.build_prompt()
        assert prompt == ""

    def test_successful_run_updates_memory(self):
        agent, runner, memory = self._make_agent(with_memory=True)
        runner.run.return_value = SessionResult(success=True, reason="completed")
        agent.run("/tmp")
        memory.update_topic.assert_called_once()

    def test_run_sends_correct_agent_type(self):
        agent, runner, _ = self._make_agent()
        runner.run.return_value = SessionResult(success=True, reason="completed")
        agent.run("/tmp")
        assert runner.run.call_args[1]["agent"] == "claude"
