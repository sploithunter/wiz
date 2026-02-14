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
