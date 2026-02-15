"""Tests for blog writer agent."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.agents.blog_writer import (
    PROPOSED_TOPIC_KEY,
    BlogWriterAgent,
)
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

    @patch("wiz.agents.blog_writer.save_all_image_prompts")
    def test_process_result_saves_image_prompts(self, mock_save):
        mock_save.return_value = [Path("/tmp/prompt.md")]

        agent, _, _ = self._make_agent()
        json_block = '```json\n{"draft_title": "My Article", "image_prompt": "A sunset"}\n```'
        result = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": json_block}}],
        )
        output = agent.process_result(result, mode="write")
        assert output["image_prompts_saved"] == 1
        mock_save.assert_called_once()

    def test_process_result_no_image_prompt(self):
        agent, _, _ = self._make_agent()
        result = SessionResult(success=True, reason="completed", events=[])
        output = agent.process_result(result, mode="write")
        assert output["image_prompts_saved"] == 0

    def test_process_result_creates_google_doc(self):
        from wiz.integrations.google_docs import DocResult, GoogleDocsClient

        gdocs = MagicMock(spec=GoogleDocsClient)
        gdocs.enabled = True
        gdocs.create_document.return_value = DocResult(
            success=True, doc_id="d1", url="https://docs.google.com/document/d/d1/edit"
        )

        agent, _, _ = self._make_agent()
        agent.google_docs = gdocs
        result = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "Some blog content"}}],
        )
        output = agent.process_result(result, mode="write", topic="My Topic")
        assert output["doc_url"] == "https://docs.google.com/document/d/d1/edit"
        gdocs.create_document.assert_called_once()
        # Disk-based image prompts should be skipped when Google Docs is enabled
        assert output["image_prompts_saved"] == 0

    def test_process_result_no_google_doc_when_disabled(self):
        agent, _, _ = self._make_agent()
        result = SessionResult(success=True, reason="completed", events=[])
        output = agent.process_result(result, mode="write")
        assert output["doc_url"] is None


class TestBlogWriterRun:
    """Tests for the run() method with mode transition logic."""

    def _make_agent(self, config=None, with_memory=True):
        runner = MagicMock(spec=SessionRunner)
        config = config or BlogWriterConfig()
        memory = MagicMock(spec=LongTermMemory) if with_memory else None
        if memory:
            memory.retrieve.return_value = []
        return BlogWriterAgent(runner, config, memory), runner, memory

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_mode_when_no_pending_topic(self, _mock_img):
        """First run with no pending topic → propose mode."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []  # no pending topic

        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "Topic: How to build AI agents"}}],
        )

        result = agent.run("/tmp")
        assert result["mode"] == "propose"
        assert result["success"] is True
        # Should have stored the proposed topic
        memory.update_topic.assert_called()
        memory.save_index.assert_called()

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_write_mode_when_pending_topic_exists(self, _mock_img):
        """Second run with pending topic → write mode."""
        agent, runner, memory = self._make_agent()
        # Simulate a pending topic in memory
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "How to build AI agents")
        ]

        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "# How to build AI agents\n\nGreat article..."}}],
        )

        result = agent.run("/tmp")
        assert result["mode"] == "write"
        assert result["success"] is True
        # Should have consumed the pending topic
        memory.delete_topic.assert_called_once_with(PROPOSED_TOPIC_KEY)
        memory.save_index.assert_called()

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_write_failure_keeps_pending_topic(self, _mock_img):
        """If write fails, don't consume the pending topic."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "How to build AI agents")
        ]

        runner.run.return_value = SessionResult(
            success=False,
            reason="timeout",
        )

        result = agent.run("/tmp")
        assert result["success"] is False
        # Should NOT have consumed the pending topic
        memory.delete_topic.assert_not_called()

    def test_run_skips_when_auto_propose_disabled_and_no_topic(self):
        """No pending topic + auto_propose_topics=False → skip."""
        config = BlogWriterConfig(auto_propose_topics=False)
        agent, runner, memory = self._make_agent(config)
        memory.retrieve.return_value = []

        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "no_pending_topics"
        runner.run.assert_not_called()

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_stores_topic_from_events(self, _mock_img):
        """Propose mode stores topic text extracted from events."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []

        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "Proposed: Building reliable AI pipelines"}}],
        )

        agent.run("/tmp")
        # Check update_topic was called with the proposed content
        calls = memory.update_topic.call_args_list
        stored_call = [c for c in calls if c[0][0] == PROPOSED_TOPIC_KEY]
        assert len(stored_call) == 1
        assert "Building reliable AI pipelines" in stored_call[0][0][2]

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_stores_topic_from_reason_fallback(self, _mock_img):
        """If no events, fall back to result.reason for topic text."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []

        runner.run.return_value = SessionResult(
            success=True,
            reason="Topic: Scaling agent architectures",
            events=[],
        )

        agent.run("/tmp")
        calls = memory.update_topic.call_args_list
        stored_call = [c for c in calls if c[0][0] == PROPOSED_TOPIC_KEY]
        assert len(stored_call) == 1
        assert "Scaling agent architectures" in stored_call[0][0][2]

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_failure_no_store(self, _mock_img):
        """If propose fails, don't store anything."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []

        runner.run.return_value = SessionResult(
            success=False,
            reason="timeout",
        )

        agent.run("/tmp")
        # update_topic should not be called with PROPOSED_TOPIC_KEY
        calls = memory.update_topic.call_args_list
        stored_call = [c for c in calls if c[0][0] == PROPOSED_TOPIC_KEY]
        assert len(stored_call) == 0

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_write_mode_uses_correct_session_name(self, _mock_img):
        """Write mode uses 'wiz-blog-write' session name."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "Test topic")
        ]
        runner.run.return_value = SessionResult(success=True, reason="done")

        agent.run("/tmp")
        call_kwargs = runner.run.call_args[1]
        assert call_kwargs["name"] == "wiz-blog-write"

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_propose_mode_uses_correct_session_name(self, _mock_img):
        """Propose mode uses 'wiz-blog-propose' session name."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = []
        runner.run.return_value = SessionResult(
            success=True, reason="done",
            events=[{"data": {"message": "topic idea"}}],
        )

        agent.run("/tmp")
        call_kwargs = runner.run.call_args[1]
        assert call_kwargs["name"] == "wiz-blog-propose"

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_without_memory_defaults_to_propose(self, _mock_img):
        """Without memory, always runs in propose mode."""
        agent, runner, _ = self._make_agent(with_memory=False)
        runner.run.return_value = SessionResult(success=True, reason="done")

        result = agent.run("/tmp")
        assert result["mode"] == "propose"

    @patch("wiz.agents.blog_writer.save_all_image_prompts", return_value=[])
    def test_run_write_mode_passes_topic_to_prompt(self, _mock_img):
        """Write mode includes the topic in the prompt."""
        agent, runner, memory = self._make_agent()
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "Building AI agents with Python")
        ]
        runner.run.return_value = SessionResult(success=True, reason="done")

        agent.run("/tmp")
        call_kwargs = runner.run.call_args[1]
        assert "Building AI agents with Python" in call_kwargs["prompt"]


class TestGetPendingTopic:
    def test_returns_none_without_memory(self):
        runner = MagicMock(spec=SessionRunner)
        agent = BlogWriterAgent(runner, BlogWriterConfig(), memory=None)
        assert agent._get_pending_topic() is None

    def test_returns_topic_when_found(self):
        runner = MagicMock(spec=SessionRunner)
        memory = MagicMock(spec=LongTermMemory)
        memory.retrieve.return_value = [
            (PROPOSED_TOPIC_KEY, "How to debug AI systems")
        ]
        agent = BlogWriterAgent(runner, BlogWriterConfig(), memory=memory)
        assert agent._get_pending_topic() == "How to debug AI systems"

    def test_returns_none_when_empty_content(self):
        runner = MagicMock(spec=SessionRunner)
        memory = MagicMock(spec=LongTermMemory)
        memory.retrieve.return_value = [(PROPOSED_TOPIC_KEY, "   ")]
        agent = BlogWriterAgent(runner, BlogWriterConfig(), memory=memory)
        assert agent._get_pending_topic() is None

    def test_returns_none_when_no_match(self):
        runner = MagicMock(spec=SessionRunner)
        memory = MagicMock(spec=LongTermMemory)
        memory.retrieve.return_value = [("other-key", "some content")]
        agent = BlogWriterAgent(runner, BlogWriterConfig(), memory=memory)
        assert agent._get_pending_topic() is None
