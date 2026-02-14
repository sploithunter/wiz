"""Tests for content pipeline."""

from unittest.mock import MagicMock, patch

from wiz.config.schema import WizConfig
from wiz.orchestrator.content_pipeline import ContentCyclePipeline


class TestContentCyclePipeline:
    @patch("wiz.orchestrator.content_pipeline.SocialManagerAgent")
    @patch("wiz.orchestrator.content_pipeline.BlogWriterAgent")
    @patch("wiz.orchestrator.content_pipeline.SessionRunner")
    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    def test_phase_ordering(self, mock_monitor, mock_client, mock_runner, mock_blog, mock_social):
        config = WizConfig()
        pipeline = ContentCyclePipeline(config)

        mock_blog.return_value = MagicMock()
        mock_blog.return_value.run.return_value = {"success": True}
        mock_social.return_value = MagicMock()
        mock_social.return_value.run.return_value = {"success": True}

        state = pipeline.run()
        assert len(state.phases) == 2
        assert state.phases[0].phase == "blog_write"
        assert state.phases[1].phase == "social_manage"

    @patch("wiz.orchestrator.content_pipeline.SocialManagerAgent")
    @patch("wiz.orchestrator.content_pipeline.BlogWriterAgent")
    @patch("wiz.orchestrator.content_pipeline.SessionRunner")
    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    def test_blog_failure_continues_to_social(
        self, mock_monitor, mock_client, mock_runner,
        mock_blog, mock_social,
    ):
        config = WizConfig()
        pipeline = ContentCyclePipeline(config)

        mock_blog.return_value = MagicMock()
        mock_blog.return_value.run.side_effect = RuntimeError("blog error")
        mock_social.return_value = MagicMock()
        mock_social.return_value.run.return_value = {"success": True}

        state = pipeline.run()
        assert len(state.phases) == 2
        assert state.phases[0].success is False
        assert state.phases[1].success is True
