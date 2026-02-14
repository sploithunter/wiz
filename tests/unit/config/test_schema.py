"""Tests for configuration schema."""

import pytest
from pydantic import ValidationError

from wiz.config.schema import (
    BugFixerConfig,
    BugHunterConfig,
    GlobalConfig,
    RepoConfig,
    WizConfig,
)


class TestGlobalConfig:
    def test_defaults(self):
        cfg = GlobalConfig()
        assert cfg.coding_agent_bridge_url == "http://127.0.0.1:4003"
        assert cfg.log_level == "info"
        assert cfg.timezone == "America/New_York"

    def test_custom_values(self):
        cfg = GlobalConfig(
            coding_agent_bridge_url="http://localhost:5000",
            log_level="debug",
        )
        assert cfg.coding_agent_bridge_url == "http://localhost:5000"
        assert cfg.log_level == "debug"


class TestRepoConfig:
    def test_required_fields(self):
        cfg = RepoConfig(name="test", path="/tmp/test", github="user/test")
        assert cfg.name == "test"
        assert cfg.enabled is True
        assert cfg.self_improve is False

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            RepoConfig()  # type: ignore[call-arg]


class TestAgentConfigs:
    def test_bug_hunter_defaults(self):
        cfg = BugHunterConfig()
        assert cfg.model == "codex"
        assert cfg.max_issues_per_run == 10
        assert cfg.require_poc is True

    def test_bug_fixer_defaults(self):
        cfg = BugFixerConfig()
        assert cfg.model == "claude"
        assert cfg.stagnation_limit == 3


class TestWizConfig:
    def test_full_defaults(self):
        cfg = WizConfig()
        assert cfg.global_.coding_agent_bridge_url == "http://127.0.0.1:4003"
        assert cfg.repos == []
        assert cfg.agents.bug_hunter.model == "codex"
        assert cfg.dev_cycle.cycle_timeout == 3600
        assert cfg.schedule.dev_cycle.enabled is True
        assert cfg.testing.run_full_suite_before_pr is True
        assert cfg.telegram.enabled is False

    def test_with_alias(self):
        cfg = WizConfig(**{"global": {"log_level": "debug"}})
        assert cfg.global_.log_level == "debug"

    def test_with_repos(self):
        cfg = WizConfig(
            repos=[
                {"name": "test", "path": "/tmp", "github": "u/t"},
            ]
        )
        assert len(cfg.repos) == 1
        assert cfg.repos[0].name == "test"

    def test_invalid_nested_raises(self):
        with pytest.raises(ValidationError):
            WizConfig(repos=[{"invalid": True}])
