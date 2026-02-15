"""Tests for CLI commands."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from wiz.cli import _resolve_wiz_dir, main


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


class TestResolveWizDir:
    """Regression tests for _resolve_wiz_dir (issue #33).

    Previously, schedule commands used config_path.parent.parent which broke
    for custom config paths not at <repo>/config/wiz.yaml.
    """

    def test_finds_repo_root_via_wake_script(self, tmp_path):
        """_resolve_wiz_dir walks up to find scripts/wake.sh."""
        repo = tmp_path / "myrepo"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "wake.sh").touch()
        (repo / "config").mkdir()
        config_path = repo / "config" / "wiz.yaml"
        config_path.touch()

        assert _resolve_wiz_dir(config_path) == repo

    def test_falls_back_to_config_parent_when_no_wake_script(self, tmp_path):
        """Without scripts/wake.sh, falls back to config's parent dir."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        config_path = custom_dir / "config.yaml"
        config_path.touch()

        assert _resolve_wiz_dir(config_path) == custom_dir

    def test_custom_config_does_not_use_parent_parent(self, tmp_path):
        """Issue #33: /tmp/repo/config.yaml must NOT resolve to /tmp."""
        repo = tmp_path / "repo"
        repo.mkdir()
        config_path = repo / "config.yaml"
        config_path.touch()

        result = _resolve_wiz_dir(config_path)
        # Old bug: config_path.parent.parent would give tmp_path (wrong)
        assert result != tmp_path
        # Should fall back to config's parent directory
        assert result == repo

    def test_nested_config_finds_ancestor_repo_root(self, tmp_path):
        """Config nested several levels deep still finds the repo root."""
        repo = tmp_path / "myrepo"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "wake.sh").touch()
        deep = repo / "a" / "b" / "c"
        deep.mkdir(parents=True)
        config_path = deep / "wiz.yaml"
        config_path.touch()

        assert _resolve_wiz_dir(config_path) == repo

    @patch("wiz.orchestrator.scheduler.LaunchdScheduler")
    def test_schedule_status_uses_resolve_wiz_dir(self, mock_sched_cls, tmp_path):
        """schedule status with a custom config uses _resolve_wiz_dir."""
        repo = tmp_path / "repo"
        repo.mkdir()
        config_path = repo / "config.yaml"
        config_path.touch()

        mock_sched_cls.return_value.status.return_value = []

        runner = CliRunner()
        with patch("wiz.config.loader.load_config") as mock_load:
            mock_cfg = MagicMock()
            mock_load.return_value = mock_cfg
            result = runner.invoke(
                main, ["--config", str(config_path), "schedule", "status"]
            )

        assert result.exit_code == 0
        # LaunchdScheduler should have been called with the repo dir, not parent.parent
        actual_wiz_dir = mock_sched_cls.call_args[0][0]
        assert actual_wiz_dir == repo
        assert actual_wiz_dir != tmp_path
