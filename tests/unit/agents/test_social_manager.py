"""Tests for social manager agent."""

from unittest.mock import MagicMock, patch

from wiz.agents.social_manager import SocialManagerAgent, _extract_json_blocks
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import SocialManagerConfig
from wiz.integrations.typefully import DraftResult, TypefullyClient
from wiz.memory.long_term import LongTermMemory


class TestSocialManagerAgent:
    def _make_agent(self, config=None, with_memory=False, typefully=None):
        runner = MagicMock(spec=SessionRunner)
        config = config or SocialManagerConfig(require_approval=False)
        memory = MagicMock(spec=LongTermMemory) if with_memory else None
        if memory:
            memory.retrieve.return_value = []
        if typefully is None:
            typefully = MagicMock(spec=TypefullyClient)
            typefully.enabled = False
        return SocialManagerAgent(runner, config, memory, typefully), runner, memory

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
        assert "JSON" in prompt or "json" in prompt
        assert "x" in prompt

    def test_prompt_no_mcp_tool_usage(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt()
        assert "typefully_create_draft" not in prompt
        assert "Use Typefully MCP tools" not in prompt

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

    @patch("wiz.agents.social_manager.save_all_image_prompts", return_value=[])
    def test_successful_run_updates_memory(self, _mock_img):
        agent, runner, memory = self._make_agent(with_memory=True)
        runner.run.return_value = SessionResult(success=True, reason="completed")
        agent.run("/tmp")
        memory.update_topic.assert_called_once()

    @patch("wiz.agents.social_manager.save_all_image_prompts", return_value=[])
    def test_run_sends_correct_agent_type(self, _mock_img):
        agent, runner, _ = self._make_agent()
        runner.run.return_value = SessionResult(success=True, reason="completed")
        agent.run("/tmp")
        assert runner.run.call_args[1]["agent"] == "claude"

    @patch("wiz.agents.social_manager.save_all_image_prompts", return_value=[])
    def test_run_creates_typefully_drafts(self, _mock_img):
        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = True
        typefully.create_draft.return_value = DraftResult(success=True, draft_id=42)

        config = SocialManagerConfig(platforms=["x", "linkedin"], require_approval=False)
        agent, runner, _ = self._make_agent(config, typefully=typefully)

        json_output = '```json\n{"draft_title": "Test", "posts": [{"text": "hello"}]}\n```'
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": json_output}}],
        )

        result = agent.run("/tmp")
        assert result["drafts_parsed"] == 1
        assert result["drafts_created"] == 1
        typefully.create_draft.assert_called_once()
        call_kwargs = typefully.create_draft.call_args[1]
        assert call_kwargs["platforms"] == ["x", "linkedin"]

    @patch("wiz.agents.social_manager.save_all_image_prompts", return_value=[])
    def test_run_skips_typefully_when_disabled(self, _mock_img):
        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = False

        agent, runner, _ = self._make_agent(typefully=typefully)
        json_output = '```json\n{"posts": [{"text": "hello"}]}\n```'
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": json_output}}],
        )

        result = agent.run("/tmp")
        assert result["drafts_parsed"] == 1
        assert result["drafts_created"] == 0
        typefully.create_draft.assert_not_called()

    @patch("wiz.agents.social_manager.save_all_image_prompts", return_value=[])
    def test_run_handles_no_json_output(self, _mock_img):
        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = True

        agent, runner, _ = self._make_agent(typefully=typefully)
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": "No posts today"}}],
        )

        result = agent.run("/tmp")
        assert result["drafts_parsed"] == 0
        assert result["drafts_created"] == 0

    @patch("wiz.agents.social_manager.save_all_image_prompts")
    def test_run_saves_image_prompts(self, mock_save):
        from pathlib import Path
        mock_save.return_value = [Path("/tmp/prompt.md")]

        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = False

        agent, runner, _ = self._make_agent(typefully=typefully)
        json_output = '```json\n{"draft_title": "Test", "posts": [{"text": "hi"}], "image_prompt": "A robot"}\n```'
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": json_output}}],
        )

        result = agent.run("/tmp")
        assert result["image_prompts_saved"] == 1
        mock_save.assert_called_once()

    @patch("wiz.agents.social_manager.save_all_image_prompts", return_value=[])
    def test_run_creates_google_docs(self, _mock_img):
        from wiz.integrations.google_docs import DocResult, GoogleDocsClient

        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = False

        gdocs = MagicMock(spec=GoogleDocsClient)
        gdocs.enabled = True
        gdocs.create_document.return_value = DocResult(
            success=True, doc_id="sd1", url="https://docs.google.com/document/d/sd1/edit"
        )

        config = SocialManagerConfig(require_approval=False)
        agent, runner, _ = self._make_agent(config, typefully=typefully)
        agent.google_docs = gdocs

        json_output = '```json\n{"draft_title": "Test", "posts": [{"text": "hi"}], "image_prompt": "A robot"}\n```'
        runner.run.return_value = SessionResult(
            success=True,
            reason="completed",
            events=[{"data": {"message": json_output}}],
        )

        result = agent.run("/tmp")
        assert len(result["doc_urls"]) == 1
        gdocs.create_document.assert_called_once()
        # Disk-based image prompts skipped when Google Docs enabled
        assert result["image_prompts_saved"] == 0

    @patch("wiz.agents.social_manager.save_all_image_prompts", return_value=[])
    def test_run_no_google_docs_when_disabled(self, _mock_img):
        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = False

        agent, runner, _ = self._make_agent(typefully=typefully)
        runner.run.return_value = SessionResult(
            success=True, reason="completed", events=[]
        )

        result = agent.run("/tmp")
        assert result["doc_urls"] == []


class TestSocialManagerApproval:
    """Tests for require_approval enforcement."""

    def _make_agent(self, config=None, typefully=None):
        runner = MagicMock(spec=SessionRunner)
        config = config or SocialManagerConfig()
        if typefully is None:
            typefully = MagicMock(spec=TypefullyClient)
            typefully.enabled = True
        return SocialManagerAgent(runner, config, typefully=typefully), runner

    def test_require_approval_blocks_run(self):
        """When require_approval=True, skip session and draft creation."""
        config = SocialManagerConfig(require_approval=True)
        agent, runner = self._make_agent(config)

        result = agent.run("/tmp")
        assert result["skipped"] is True
        assert result["reason"] == "awaiting_approval"
        runner.run.assert_not_called()

    @patch("wiz.agents.social_manager.save_all_image_prompts", return_value=[])
    def test_no_approval_allows_run(self, _mock_img):
        """When require_approval=False, session runs normally."""
        config = SocialManagerConfig(require_approval=False)
        typefully = MagicMock(spec=TypefullyClient)
        typefully.enabled = False
        agent, runner = self._make_agent(config, typefully=typefully)

        runner.run.return_value = SessionResult(success=True, reason="completed")

        result = agent.run("/tmp")
        assert result["success"] is True
        runner.run.assert_called_once()

    def test_require_approval_default_is_true(self):
        """Default config has require_approval=True."""
        config = SocialManagerConfig()
        assert config.require_approval is True


class TestExtractJsonBlocks:
    def test_single_block(self):
        text = 'Here is a post:\n```json\n{"posts": [{"text": "hello"}]}\n```'
        blocks = _extract_json_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["posts"][0]["text"] == "hello"

    def test_multiple_blocks(self):
        text = (
            '```json\n{"draft_title": "A", "posts": [{"text": "one"}]}\n```\n'
            'Some text\n'
            '```json\n{"draft_title": "B", "posts": [{"text": "two"}]}\n```'
        )
        blocks = _extract_json_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["draft_title"] == "A"
        assert blocks[1]["draft_title"] == "B"

    def test_invalid_json_skipped(self):
        text = '```json\n{invalid json}\n```'
        blocks = _extract_json_blocks(text)
        assert len(blocks) == 0

    def test_no_json_blocks(self):
        text = "Just some plain text with no code blocks"
        blocks = _extract_json_blocks(text)
        assert len(blocks) == 0

    def test_non_dict_json_skipped(self):
        text = '```json\n["a", "b"]\n```'
        blocks = _extract_json_blocks(text)
        assert len(blocks) == 0


class TestParsePostsFromResult:
    def test_parses_from_events(self):
        result = SessionResult(
            success=True,
            reason="done",
            events=[
                {"data": {"message": '```json\n{"posts": [{"text": "hi"}]}\n```'}},
            ],
        )
        blocks = SocialManagerAgent._parse_posts_from_result(result)
        assert len(blocks) == 1

    def test_fallback_to_reason(self):
        result = SessionResult(
            success=True,
            reason='```json\n{"posts": [{"text": "from reason"}]}\n```',
            events=[],
        )
        blocks = SocialManagerAgent._parse_posts_from_result(result)
        assert len(blocks) == 1

    def test_parses_from_event_text_field(self):
        result = SessionResult(
            success=True,
            reason="done",
            events=[
                {"text": '```json\n{"posts": [{"text": "from text"}]}\n```'},
            ],
        )
        blocks = SocialManagerAgent._parse_posts_from_result(result)
        assert len(blocks) == 1
