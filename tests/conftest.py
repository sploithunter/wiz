"""Shared test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def sample_config_yaml(tmp_path: Path) -> Path:
    """Create a minimal valid config YAML file."""
    config = tmp_path / "wiz.yaml"
    config.write_text(
        """\
global:
  coding_agent_bridge_url: "http://127.0.0.1:4003"
  log_level: "info"

repos:
  - name: "test-repo"
    path: "/tmp/test-repo"
    github: "user/test-repo"
    enabled: true
"""
    )
    return config


@pytest.fixture
def empty_config_yaml(tmp_path: Path) -> Path:
    """Create an empty config YAML file."""
    config = tmp_path / "wiz.yaml"
    config.write_text("{}\n")
    return config
