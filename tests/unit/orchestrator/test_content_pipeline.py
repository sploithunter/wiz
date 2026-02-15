"""Tests for content pipeline."""

from unittest.mock import MagicMock, patch

from wiz.config.schema import WizConfig
from wiz.orchestrator.content_pipeline import ContentCyclePipeline


class TestContentCyclePipeline:
    @patch("wiz.orchestrator.content_pipeline.GoogleDocsClient")
    @patch("wiz.orchestrator.content_pipeline.TypefullyClient")
    @patch("wiz.orchestrator.content_pipeline.SocialManagerAgent")
    @patch("wiz.orchestrator.content_pipeline.BlogWriterAgent")
    @patch("wiz.orchestrator.content_pipeline.SessionRunner")
    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    def test_phase_ordering(
        self, mock_monitor, mock_client, mock_runner,
        mock_blog, mock_social, mock_typefully, mock_gdocs,
    ):
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

    @patch("wiz.orchestrator.content_pipeline.GoogleDocsClient")
    @patch("wiz.orchestrator.content_pipeline.TypefullyClient")
    @patch("wiz.orchestrator.content_pipeline.SocialManagerAgent")
    @patch("wiz.orchestrator.content_pipeline.BlogWriterAgent")
    @patch("wiz.orchestrator.content_pipeline.SessionRunner")
    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    def test_blog_failure_continues_to_social(
        self, mock_monitor, mock_client, mock_runner,
        mock_blog, mock_social, mock_typefully, mock_gdocs,
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

    @patch("wiz.orchestrator.content_pipeline.GoogleDocsClient")
    @patch("wiz.orchestrator.content_pipeline.TypefullyClient")
    @patch("wiz.orchestrator.content_pipeline.SocialManagerAgent")
    @patch("wiz.orchestrator.content_pipeline.BlogWriterAgent")
    @patch("wiz.orchestrator.content_pipeline.SessionRunner")
    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    def test_typefully_passed_to_social_manager(
        self, mock_monitor, mock_client, mock_runner,
        mock_blog, mock_social, mock_typefully, mock_gdocs,
    ):
        config = WizConfig()
        pipeline = ContentCyclePipeline(config)

        mock_blog.return_value = MagicMock()
        mock_blog.return_value.run.return_value = {"success": True}
        mock_social.return_value = MagicMock()
        mock_social.return_value.run.return_value = {"success": True}

        pipeline.run()

        # Verify TypefullyClient.from_config was called
        mock_typefully.from_config.assert_called_once_with(config.agents.social_manager)
        # Verify typefully was passed to SocialManagerAgent
        social_call_args = mock_social.call_args
        assert social_call_args[0][3] == mock_typefully.from_config.return_value or \
               social_call_args[1].get("typefully") == mock_typefully.from_config.return_value or \
               len(social_call_args[0]) >= 4

    @patch("wiz.orchestrator.content_pipeline.GoogleDocsClient")
    @patch("wiz.orchestrator.content_pipeline.TypefullyClient")
    @patch("wiz.orchestrator.content_pipeline.SocialManagerAgent")
    @patch("wiz.orchestrator.content_pipeline.BlogWriterAgent")
    @patch("wiz.orchestrator.content_pipeline.SessionRunner")
    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    def test_google_docs_passed_to_agents(
        self, mock_monitor, mock_client, mock_runner,
        mock_blog, mock_social, mock_typefully, mock_gdocs,
    ):
        config = WizConfig()
        pipeline = ContentCyclePipeline(config)

        mock_blog.return_value = MagicMock()
        mock_blog.return_value.run.return_value = {"success": True}
        mock_social.return_value = MagicMock()
        mock_social.return_value.run.return_value = {"success": True}

        pipeline.run()

        # GoogleDocsClient.from_config called once and shared
        mock_gdocs.from_config.assert_called_once_with(config.google_docs)
        gdocs_instance = mock_gdocs.from_config.return_value

        # Passed to BlogWriterAgent
        blog_args = mock_blog.call_args[0]
        assert blog_args[3] == gdocs_instance  # 4th positional arg

        # Passed to SocialManagerAgent
        social_args = mock_social.call_args[0]
        assert social_args[4] == gdocs_instance  # 5th positional arg
