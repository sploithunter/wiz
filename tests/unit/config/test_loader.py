"""Tests for configuration loader."""

from pathlib import Path

import pytest

from wiz.config.loader import load_config


class TestLoadConfig:
    def test_load_from_file(self, sample_config_yaml: Path):
        cfg = load_config(sample_config_yaml)
        assert cfg.global_.coding_agent_bridge_url == "http://127.0.0.1:4003"
        assert len(cfg.repos) == 1
        assert cfg.repos[0].name == "test-repo"

    def test_missing_file_returns_defaults(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.yaml")
        assert cfg.global_.coding_agent_bridge_url == "http://127.0.0.1:4003"
        assert cfg.repos == []

    def test_none_path_returns_defaults(self):
        cfg = load_config(None)
        assert cfg.repos == []

    def test_empty_yaml_returns_defaults(self, empty_config_yaml: Path):
        cfg = load_config(empty_config_yaml)
        assert cfg.repos == []

    def test_malformed_yaml_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(":\n  :\n    - :\n      :::invalid")
        with pytest.raises(ValueError, match="Malformed YAML"):
            load_config(bad)

    def test_load_full_config(self):
        cfg = load_config(Path("/Users/jason/Documents/wiz/config/wiz.yaml"))
        assert len(cfg.repos) >= 3
        assert cfg.repos[0].name == "wiz"
        assert cfg.repos[0].self_improve is True
        assert cfg.agents.bug_hunter.model == "codex"

    def test_directory_path_returns_defaults(self, tmp_path: Path):
        cfg = load_config(tmp_path)
        assert cfg.repos == []

    def test_overrides(self, tmp_path: Path):
        config = tmp_path / "custom.yaml"
        config.write_text(
            """\
global:
  log_level: "debug"
agents:
  bug_hunter:
    max_issues_per_run: 5
"""
        )
        cfg = load_config(config)
        assert cfg.global_.log_level == "debug"
        assert cfg.agents.bug_hunter.max_issues_per_run == 5
        # Other defaults preserved
        assert cfg.agents.bug_fixer.model == "claude"
