"""Tests for blog writer agent."""

from unittest.mock import MagicMock

from wiz.agents.blog_writer import BlogWriterAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BlogWriterConfig
from wiz.memory.long_term import LongTermMemory


class TestBlogWriterAgent:
    def _make_agent(self, config=None, with_memory=False):
        runner = MagicMock(spec=SessionRunner)
        config = config or BlogWriterConfig()
        memory = MagicMock(spec=LongTermMemory) if with_memory else None
        if memory:
            memory.retrieve.return_value = [("blog-topic", "Previous post about X")]
        return BlogWriterAgent(runner, config, memory), runner, memory

    def test_topic_proposal_prompt(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt(mode="propose")
        assert "Propose Blog Topics" in prompt

    def test_draft_generation_prompt(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt(mode="write", topic="Building AI Agents")
        assert "Building AI Agents" in prompt
        assert "Write Blog Draft" in prompt

    def test_memory_dedup(self):
        agent, _, memory = self._make_agent(with_memory=True)
        prompt = agent.build_prompt(mode="propose")
        assert "Recent Topics" in prompt
        memory.retrieve.assert_called()

    def test_process_result_updates_memory(self):
        agent, _, memory = self._make_agent(with_memory=True)
        result = SessionResult(success=True, reason="completed")
        agent.process_result(result, topic="Test Topic", mode="write")
        memory.update_topic.assert_called_once()

    def test_process_result_failure(self):
        agent, _, _ = self._make_agent()
        result = SessionResult(success=False, reason="timeout")
        output = agent.process_result(result)
        assert output["success"] is False
