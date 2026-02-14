"""Tests for self-improvement guard."""

from wiz.orchestrator.self_improve import SelfImprovementGuard


class TestSelfImprovementGuard:
    def test_config_yaml_protected(self):
        guard = SelfImprovementGuard()
        assert guard.is_protected("config/wiz.yaml") is True

    def test_claude_md_protected(self):
        guard = SelfImprovementGuard()
        assert guard.is_protected("CLAUDE.md") is True

    def test_agent_claude_md_protected(self):
        guard = SelfImprovementGuard()
        assert guard.is_protected("agents/bug-hunter/CLAUDE.md") is True
        assert guard.is_protected("agents/reviewer/CLAUDE.md") is True

    def test_escalation_protected(self):
        guard = SelfImprovementGuard()
        assert guard.is_protected("src/wiz/orchestrator/escalation.py") is True

    def test_schema_protected(self):
        guard = SelfImprovementGuard()
        assert guard.is_protected("src/wiz/config/schema.py") is True

    def test_regular_file_not_protected(self):
        guard = SelfImprovementGuard()
        assert guard.is_protected("src/wiz/agents/bug_hunter.py") is False
        assert guard.is_protected("tests/test_import.py") is False
        assert guard.is_protected("README.md") is False

    def test_validate_mixed_changes(self):
        guard = SelfImprovementGuard()
        result = guard.validate_changes([
            "src/wiz/agents/bug_hunter.py",
            "config/wiz.yaml",
            "tests/test_new.py",
        ])
        assert result["needs_human_review"] is True
        assert "config/wiz.yaml" in result["protected_files"]
        assert len(result["non_protected_files"]) == 2

    def test_validate_no_protected(self):
        guard = SelfImprovementGuard()
        result = guard.validate_changes([
            "src/wiz/agents/bug_hunter.py",
            "tests/test_new.py",
        ])
        assert result["needs_human_review"] is False
        assert result["protected_files"] == []

    def test_custom_patterns(self):
        guard = SelfImprovementGuard(patterns=["*.secret", "internal/*"])
        assert guard.is_protected("my.secret") is True
        assert guard.is_protected("internal/config.py") is True
        assert guard.is_protected("public/readme.md") is False
