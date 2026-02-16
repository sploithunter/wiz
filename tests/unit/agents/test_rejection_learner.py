"""Tests for rejection learner agent."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.agents.rejection_learner import RejectionLearnerAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import RejectionLearnerConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.memory.rejection_journal import RejectionJournal


class TestRejectionLearnerAgent:
    def _make_agent(self, tmp_path: Path, config: RejectionLearnerConfig | None = None):
        runner = MagicMock(spec=SessionRunner)
        config = config or RejectionLearnerConfig()
        journal = RejectionJournal(tmp_path / "rejections")
        github = MagicMock(spec=GitHubIssues)
        agent = RejectionLearnerAgent(runner, config, journal, github)
        return agent, runner, journal, github

    def test_build_prompt_includes_journal_summary(self, tmp_path: Path):
        agent, _, journal, _ = self._make_agent(tmp_path)
        journal.record("wiz", 42, "fix/42", "Missing edge case tests")
        journal.record("wiz", 55, "fix/55", "No error handling")

        prompt = agent.build_prompt()
        assert "wiz#42" in prompt
        assert "wiz#55" in prompt
        assert "Missing edge case tests" in prompt

    @patch("wiz.agents.rejection_learner.AGENT_CLAUDE_MD_PATHS", {})
    def test_build_prompt_handles_missing_claude_md(self, tmp_path: Path):
        agent, _, _, _ = self._make_agent(tmp_path)
        prompt = agent.build_prompt()
        assert "No CLAUDE.md files found" in prompt

    def test_build_prompt_includes_claude_md_content(self, tmp_path: Path):
        # Create a fake CLAUDE.md
        claude_md = tmp_path / "agents" / "bug-fixer" / "CLAUDE.md"
        claude_md.parent.mkdir(parents=True)
        claude_md.write_text("# Bug Fixer Instructions\nAlways run tests.")

        with patch("wiz.agents.rejection_learner.AGENT_CLAUDE_MD_PATHS", {"bug-fixer": claude_md}):
            config = RejectionLearnerConfig(target_agents=["bug-fixer"])
            agent, _, _, _ = self._make_agent(tmp_path, config)
            prompt = agent.build_prompt()

        assert "Bug Fixer Instructions" in prompt
        assert "Always run tests" in prompt

    def test_process_result_creates_issue(self, tmp_path: Path):
        agent, _, _, github = self._make_agent(tmp_path)
        github.create_issue.return_value = "https://github.com/test/repo/issues/99"

        result = SessionResult(
            success=True, reason="completed", events=[],
            output='```json\n{"patterns": [{"name": "missing-tests", "count": 3, "description": "Tests not written", "examples": ["#12", "#34"]}], "proposed_additions": [{"file": "agents/bug-fixer/CLAUDE.md", "section": "## Testing", "addition": "Always verify edge cases"}]}\n```',
        )
        outcome = agent.process_result(result)

        assert outcome["success"] is True
        assert outcome["patterns_found"] == 1
        assert outcome["proposals"] == 1
        assert outcome["issue_url"] == "https://github.com/test/repo/issues/99"
        github.create_issue.assert_called_once()
        call_kwargs = github.create_issue.call_args[1]
        assert "wiz-improvement" in call_kwargs["labels"]

    def test_process_result_no_patterns(self, tmp_path: Path):
        agent, _, _, github = self._make_agent(tmp_path)

        result = SessionResult(
            success=True, reason="completed", events=[],
            output='```json\n{"patterns": [], "proposed_additions": []}\n```',
        )
        outcome = agent.process_result(result)

        assert outcome["success"] is True
        assert outcome["patterns_found"] == 0
        assert outcome["proposals"] == 0
        github.create_issue.assert_not_called()

    def test_process_result_failure(self, tmp_path: Path):
        agent, _, _, github = self._make_agent(tmp_path)

        result = SessionResult(success=False, reason="timeout", events=[])
        outcome = agent.process_result(result)

        assert outcome["success"] is False
        github.create_issue.assert_not_called()

    def test_parse_output_valid_json(self):
        text = 'Some analysis\n```json\n{"patterns": [{"name": "test"}], "proposed_additions": []}\n```\nEnd'
        parsed = RejectionLearnerAgent._parse_output(text)
        assert parsed is not None
        assert len(parsed["patterns"]) == 1

    def test_parse_output_no_json(self):
        assert RejectionLearnerAgent._parse_output("no json here") is None

    def test_parse_output_invalid_json(self):
        assert RejectionLearnerAgent._parse_output("```json\n{bad}\n```") is None
