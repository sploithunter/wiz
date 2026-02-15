"""Tests for GitHub PRs coordination."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from wiz.coordination.github_prs import GitHubPRs


class TestGitHubPRs:
    def setup_method(self):
        self.prs = GitHubPRs("user/repo")

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_create_pr(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="https://github.com/user/repo/pull/1\n",
            returncode=0,
        )
        url = self.prs.create_pr("Fix bug", "Details", head="fix/123")
        assert url == "https://github.com/user/repo/pull/1"

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_create_pr_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
        assert self.prs.create_pr("title", "body", head="branch") is None

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_list_prs(self, mock_run):
        prs = [{"number": 1, "title": "PR 1", "state": "open"}]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(prs), returncode=0
        )
        result = self.prs.list_prs()
        assert len(result) == 1

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_get_pr(self, mock_run):
        pr = {"number": 1, "title": "PR", "state": "open"}
        mock_run.return_value = MagicMock(
            stdout=json.dumps(pr), returncode=0
        )
        result = self.prs.get_pr(1)
        assert result["number"] == 1

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_get_pr_not_found(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
        assert self.prs.get_pr(999) is None


class TestMergePR:
    def setup_method(self):
        self.prs = GitHubPRs("user/repo")

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_merge_pr_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert self.prs.merge_pr(42) is True
        cmd = mock_run.call_args[0][0]
        assert "merge" in cmd
        assert "42" in cmd
        assert "--squash" in cmd
        assert "--delete-branch" in cmd

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_merge_pr_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
        assert self.prs.merge_pr(42) is False

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_merge_pr_no_delete_branch(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        self.prs.merge_pr(42, delete_branch=False)
        cmd = mock_run.call_args[0][0]
        assert "--delete-branch" not in cmd


class TestGhMissing:
    """Regression tests for missing gh CLI (FileNotFoundError)."""

    def setup_method(self):
        self.prs = GitHubPRs("user/repo")

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_list_prs_returns_empty_when_gh_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError(2, "No such file or directory")
        assert self.prs.list_prs() == []

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_create_pr_returns_none_when_gh_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError(2, "No such file or directory")
        assert self.prs.create_pr("title", "body", head="branch") is None

    @patch("wiz.coordination.github_prs.subprocess.run")
    def test_get_pr_returns_none_when_gh_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError(2, "No such file or directory")
        assert self.prs.get_pr(1) is None
