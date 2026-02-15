"""Tests for GitHub issues coordination."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from wiz.coordination.github_issues import GitHubIssues


class TestGitHubIssues:
    def setup_method(self):
        self.gh = GitHubIssues("user/repo")

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_create_issue(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="https://github.com/user/repo/issues/1\n",
            returncode=0,
        )
        url = self.gh.create_issue("Bug title", "Bug body", labels=["wiz-bug"])
        assert url == "https://github.com/user/repo/issues/1"
        cmd = mock_run.call_args[0][0]
        assert "issue" in cmd
        assert "create" in cmd
        assert "--label" in cmd

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_create_issue_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
        assert self.gh.create_issue("title", "body") is None

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_list_issues(self, mock_run):
        issues = [
            {"number": 1, "title": "Bug 1", "labels": [{"name": "wiz-bug"}]},
            {"number": 2, "title": "Bug 2", "labels": [{"name": "wiz-bug"}]},
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(issues), returncode=0
        )
        result = self.gh.list_issues(labels=["wiz-bug"])
        assert len(result) == 2

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_list_issues_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        assert self.gh.list_issues() == []

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_add_comment(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert self.gh.add_comment(1, "Fix applied") is True

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_update_labels(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert self.gh.update_labels(1, add=["needs-fix"], remove=["needs-triage"]) is True
        # ensure_labels (1 call) + add-label + remove-label = 3
        assert mock_run.call_count == 3

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_close_issue(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert self.gh.close_issue(1) is True

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_reopen_issue(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert self.gh.reopen_issue(1) is True

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_check_duplicate_found(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps([{"title": "Existing Bug"}]),
            returncode=0,
        )
        assert self.gh.check_duplicate("existing bug") is True

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_check_duplicate_not_found(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps([{"title": "Other Bug"}]),
            returncode=0,
        )
        assert self.gh.check_duplicate("new bug") is False

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_get_issue_success(self, mock_run):
        issue_data = {"number": 42, "title": "Bug", "labels": [], "state": "OPEN"}
        mock_run.return_value = MagicMock(
            stdout=json.dumps(issue_data), returncode=0
        )
        result = self.gh.get_issue(42)
        assert result is not None
        assert result["number"] == 42
        cmd = mock_run.call_args[0][0]
        assert "view" in cmd

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_get_issue_not_found(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
        assert self.gh.get_issue(999) is None

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_get_issue_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 30)
        assert self.gh.get_issue(1) is None

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_timeout_handling(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 30)
        assert self.gh.create_issue("title", "body") is None
        assert self.gh.list_issues() == []
        assert self.gh.add_comment(1, "text") is False


class TestAuthorFiltering:
    """Tests for procedural author allowlist — security boundary."""

    def test_no_allowlist_passes_all(self):
        gh = GitHubIssues("user/repo")
        issues = [
            {"number": 1, "author": {"login": "anyone"}, "title": "Bug"},
            {"number": 2, "author": {"login": "attacker"}, "title": "Hack"},
        ]
        assert len(gh._filter_by_author(issues)) == 2

    def test_allowlist_blocks_unauthorized(self):
        gh = GitHubIssues("user/repo", allowed_authors=["trusted-user"])
        issues = [
            {"number": 1, "author": {"login": "trusted-user"}, "title": "Real bug"},
            {"number": 2, "author": {"login": "attacker"}, "title": "Inject me"},
        ]
        result = gh._filter_by_author(issues)
        assert len(result) == 1
        assert result[0]["number"] == 1

    def test_allowlist_case_insensitive(self):
        gh = GitHubIssues("user/repo", allowed_authors=["TrustedUser"])
        issues = [
            {"number": 1, "author": {"login": "trusteduser"}, "title": "Bug"},
        ]
        assert len(gh._filter_by_author(issues)) == 1

    def test_allowlist_blocks_missing_author(self):
        gh = GitHubIssues("user/repo", allowed_authors=["trusted"])
        issues = [
            {"number": 1, "title": "No author field"},
        ]
        assert len(gh._filter_by_author(issues)) == 0

    def test_allowlist_handles_null_author(self):
        """Regression: author=null (deleted/bot accounts) must not crash."""
        gh = GitHubIssues("user/repo", allowed_authors=["alice"])
        issues = [
            {"number": 1, "title": "bug", "author": None},
            {"number": 2, "title": "ok", "author": {"login": "alice"}},
        ]
        result = gh._filter_by_author(issues)
        assert len(result) == 1
        assert result[0]["number"] == 2

    def test_allowlist_blocks_empty_login(self):
        gh = GitHubIssues("user/repo", allowed_authors=["trusted"])
        issues = [
            {"number": 1, "author": {"login": ""}, "title": "Empty login"},
        ]
        assert len(gh._filter_by_author(issues)) == 0

    def test_allowlist_multiple_allowed(self):
        gh = GitHubIssues("user/repo", allowed_authors=["alice", "bob"])
        issues = [
            {"number": 1, "author": {"login": "alice"}, "title": "A"},
            {"number": 2, "author": {"login": "bob"}, "title": "B"},
            {"number": 3, "author": {"login": "eve"}, "title": "C"},
        ]
        result = gh._filter_by_author(issues)
        assert len(result) == 2
        assert {r["number"] for r in result} == {1, 2}

    def test_empty_allowlist_means_no_filter(self):
        """Empty list = no allowlist = accept all (backward compat)."""
        gh = GitHubIssues("user/repo", allowed_authors=[])
        assert gh._allowed_authors is None
        issues = [{"number": 1, "author": {"login": "anyone"}}]
        assert len(gh._filter_by_author(issues)) == 1

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_list_issues_filters_by_author(self, mock_run):
        gh = GitHubIssues("user/repo", allowed_authors=["trusted"])
        issues = [
            {"number": 1, "author": {"login": "trusted"}, "title": "OK"},
            {"number": 2, "author": {"login": "attacker"}, "title": "Inject"},
        ]
        mock_run.return_value = MagicMock(stdout=json.dumps(issues), returncode=0)
        result = gh.list_issues(labels=["wiz-bug"])
        assert len(result) == 1
        assert result[0]["number"] == 1

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_list_issues_includes_author_in_json_fields(self, mock_run):
        gh = GitHubIssues("user/repo")
        mock_run.return_value = MagicMock(stdout="[]", returncode=0)
        gh.list_issues()
        cmd = mock_run.call_args[0][0]
        json_arg_idx = cmd.index("--json")
        fields = cmd[json_arg_idx + 1]
        assert "author" in fields

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_get_issue_rejects_unauthorized(self, mock_run):
        gh = GitHubIssues("user/repo", allowed_authors=["trusted"])
        issue_data = {
            "number": 42, "title": "Injected", "labels": [],
            "state": "OPEN", "author": {"login": "attacker"},
        }
        mock_run.return_value = MagicMock(
            stdout=json.dumps(issue_data), returncode=0
        )
        assert gh.get_issue(42) is None

    @patch("wiz.coordination.github_issues.subprocess.run")
    def test_get_issue_allows_authorized(self, mock_run):
        gh = GitHubIssues("user/repo", allowed_authors=["trusted"])
        issue_data = {
            "number": 42, "title": "Legit", "labels": [],
            "state": "OPEN", "author": {"login": "trusted"},
        }
        mock_run.return_value = MagicMock(
            stdout=json.dumps(issue_data), returncode=0
        )
        result = gh.get_issue(42)
        assert result is not None
        assert result["number"] == 42
