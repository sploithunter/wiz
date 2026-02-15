"""E2E test for content cycle pipeline with mocked bridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiz.bridge.types import SessionResult
from wiz.config.schema import WizConfig
from wiz.orchestrator.content_pipeline import ContentCyclePipeline


@pytest.mark.e2e
class TestContentCycleE2E:
    """Full content pipeline test against mocked bridge."""

    def _make_config(self, tmp_path: Path) -> WizConfig:
        return WizConfig(
            repos=[{
                "name": "test-repo",
                "path": str(tmp_path),
                "github": "owner/test-repo",
                "enabled": True,
            }],
            memory={"long_term_dir": str(tmp_path / "memory")},
        )

    def _mock_runner_result(self) -> SessionResult:
        return SessionResult(
            success=True,
            reason="completed",
            elapsed=5.0,
            events=[],
        )

    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.content_pipeline.GoogleDocsClient")
    @patch("wiz.orchestrator.content_pipeline.TypefullyClient")
    def test_full_content_cycle(
        self,
        mock_typefully_cls,
        mock_gdocs_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)

        # Create memory directory
        (tmp_path / "memory").mkdir()

        # Configure mocks
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.create_session.return_value = "sess-1"
        mock_client.send_prompt.return_value = True
        mock_client.get_session.return_value = {"status": "idle"}
        mock_client.delete_session.return_value = True
        mock_client.cleanup_all_sessions.return_value = 0
        mock_client_cls.return_value = mock_client

        mock_monitor = MagicMock()
        mock_monitor.wait_for_stop.return_value = True
        mock_monitor.stop_detected = True
        mock_monitor.events = []
        mock_monitor_cls.return_value = mock_monitor

        mock_gdocs = MagicMock()
        mock_gdocs.enabled = False
        mock_gdocs_cls.from_config.return_value = mock_gdocs

        mock_typefully = MagicMock()
        mock_typefully.enabled = False
        mock_typefully_cls.from_config.return_value = mock_typefully

        pipeline = ContentCyclePipeline(config)
        state = pipeline.run()

        assert state.repo == "content"
        assert len(state.phases) == 2
        phase_names = [p.phase for p in state.phases]
        assert phase_names == ["blog_write", "social_manage"]

    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.content_pipeline.GoogleDocsClient")
    @patch("wiz.orchestrator.content_pipeline.TypefullyClient")
    def test_blog_failure_continues_to_social(
        self,
        mock_typefully_cls,
        mock_gdocs_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)
        (tmp_path / "memory").mkdir()

        # Blog writer will fail, social manager should still run
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.create_session.side_effect = Exception("bridge down")
        mock_client_cls.return_value = mock_client

        mock_monitor = MagicMock()
        mock_monitor_cls.return_value = mock_monitor

        mock_gdocs = MagicMock()
        mock_gdocs.enabled = False
        mock_gdocs_cls.from_config.return_value = mock_gdocs

        mock_typefully = MagicMock()
        mock_typefully.enabled = False
        mock_typefully_cls.from_config.return_value = mock_typefully

        pipeline = ContentCyclePipeline(config)
        state = pipeline.run()

        # Both phases should be recorded even though blog failed
        assert len(state.phases) == 2
        assert state.phases[0].phase == "blog_write"
        assert state.phases[0].success is False
        assert state.phases[1].phase == "social_manage"

    @patch("wiz.orchestrator.content_pipeline.BridgeClient")
    @patch("wiz.orchestrator.content_pipeline.BridgeEventMonitor")
    @patch("wiz.orchestrator.content_pipeline.GoogleDocsClient")
    @patch("wiz.orchestrator.content_pipeline.TypefullyClient")
    def test_elapsed_time_tracked(
        self,
        mock_typefully_cls,
        mock_gdocs_cls,
        mock_monitor_cls,
        mock_client_cls,
        tmp_path,
    ):
        config = self._make_config(tmp_path)
        (tmp_path / "memory").mkdir()

        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.create_session.return_value = "sess-1"
        mock_client.send_prompt.return_value = True
        mock_client.get_session.return_value = {"status": "idle"}
        mock_client.delete_session.return_value = True
        mock_client.cleanup_all_sessions.return_value = 0
        mock_client_cls.return_value = mock_client

        mock_monitor = MagicMock()
        mock_monitor.wait_for_stop.return_value = True
        mock_monitor.stop_detected = True
        mock_monitor.events = []
        mock_monitor_cls.return_value = mock_monitor

        mock_gdocs = MagicMock()
        mock_gdocs.enabled = False
        mock_gdocs_cls.from_config.return_value = mock_gdocs

        mock_typefully = MagicMock()
        mock_typefully.enabled = False
        mock_typefully_cls.from_config.return_value = mock_typefully

        pipeline = ContentCyclePipeline(config)
        state = pipeline.run()

        assert state.total_elapsed >= 0
