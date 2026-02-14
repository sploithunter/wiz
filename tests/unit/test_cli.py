"""Tests for CLI commands."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from wiz.cli import main


class TestCLI:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Wiz" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_status(self):
        runner = CliRunner()
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "Wiz v0.1.0" in result.output

    def test_run_group(self):
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "dev-cycle" in result.output
        assert "content-cycle" in result.output
        assert "feature-cycle" in result.output

    def test_schedule_group(self):
        runner = CliRunner()
        result = runner.invoke(main, ["schedule", "--help"])
        assert result.exit_code == 0
        assert "install" in result.output
        assert "uninstall" in result.output
        assert "status" in result.output

    def test_schedule_status(self):
        runner = CliRunner()
        result = runner.invoke(main, ["schedule", "status"])
        assert result.exit_code == 0

    @patch("wiz.orchestrator.content_pipeline.ContentCyclePipeline")
    @patch("wiz.config.loader.load_config")
    def test_content_cycle_runs(self, mock_load, mock_pipeline_cls):
        mock_state = MagicMock()
        mock_state.summary.return_value = "content cycle complete"
        mock_pipeline_cls.return_value.run.return_value = mock_state
        runner = CliRunner()
        result = runner.invoke(main, ["run", "content-cycle"])
        assert result.exit_code == 0
        assert "content" in result.output
