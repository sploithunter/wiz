"""Tests for blog writer agent."""

from pathlib import Path
from unittest.mock import MagicMock, patch

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
