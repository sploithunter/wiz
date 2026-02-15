"""Tests for bug hunter agent."""

from unittest.mock import MagicMock

from wiz.agents.bug_hunter import BugHunterAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BugHunterConfig
from wiz.coordination.github_issues import GitHubIssues


class TestBugHunterAgent:
    def _make_agent(self, config=None):
        runner = MagicMock(spec=SessionRunner)
        config = config or BugHunterConfig()
        github = MagicMock(spec=GitHubIssues)
        return BugHunterAgent(runner, config, github), runner, github

    def test_prompt_includes_existing_issues(self):
        agent, _, _ = self._make_agent()
        existing = [{"title": "Bug A"}, {"title": "Bug B"}]
        prompt = agent.build_prompt(existing_issues=existing)
        assert "Bug A" in prompt
        assert "Bug B" in prompt
        assert "do NOT duplicate" in prompt

    def test_prompt_respects_max_issues(self):
        config = BugHunterConfig(max_issues_per_run=5)
        agent, _, _ = self._make_agent(config)
        prompt = agent.build_prompt()
        assert "5" in prompt

    def test_prompt_without_existing_issues(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt()
        assert "Analyze this repository" in prompt

    def test_agent_type_is_codex(self):
        agent, _, _ = self._make_agent()
        assert agent.agent_type == "codex"

    def test_process_result_success(self):
        agent, _, github = self._make_agent()
        github.list_issues.return_value = [
            {"number": 1, "title": "[P2] Bug"},
            {"number": 2, "title": "[P3] Another Bug"},
        ]
        result = SessionResult(success=True, reason="completed", elapsed=60)
        output = agent.process_result(result)
        assert output["success"] is True
        assert output["bugs_found"] == 2

    def test_process_result_failure(self):
        agent, _, _ = self._make_agent()
        result = SessionResult(success=False, reason="timeout", elapsed=600)
        output = agent.process_result(result)
        assert output["success"] is False
        assert output["bugs_found"] == 0

    def test_run_full_flow(self):
        agent, runner, github = self._make_agent()
        runner.run.return_value = SessionResult(
            success=True, reason="completed", elapsed=30
        )
        github.list_issues.return_value = [{"number": 1, "title": "Bug"}]

        output = agent.run("/tmp/repo", timeout=120)
        assert output["success"] is True
        runner.run.assert_called_once()
        assert runner.run.call_args[1]["agent"] == "codex"

    def test_docs_audit_in_prompt_by_default(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt()
        assert "Documentation Audit" in prompt
        assert "[P4] Docs:" in prompt
        assert "wiz-bug,docs" in prompt

    def test_docs_audit_disabled(self):
        config = BugHunterConfig(audit_docs=False)
        agent, _, _ = self._make_agent(config)
        prompt = agent.build_prompt()
        assert "Documentation Audit" not in prompt

    def test_docs_audit_mentions_key_checks(self):
        agent, _, _ = self._make_agent()
        prompt = agent.build_prompt()
        assert "README" in prompt
        assert "docstrings" in prompt
        assert "schema.py" in prompt

    def test_model_passed_to_runner(self):
        """Regression test for issue #53: model config must reach runner.run."""
        config = BugHunterConfig(model="custom-model")
        agent, runner, github = self._make_agent(config)
        runner.run.return_value = SessionResult(success=True, reason="completed")
        github.list_issues.return_value = []

        agent.run("/tmp")
        assert runner.run.call_args[1]["model"] == "custom-model"
