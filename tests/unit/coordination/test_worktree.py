"""Tests for worktree manager."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.coordination.worktree import WorktreeManager


class TestWorktreeManager:
    def setup_method(self):
        self.wt = WorktreeManager(Path("/tmp/repo"))

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_create(self, mock_run):
        """When branch does not exist, create() uses -b to create it."""
        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd:
                raise subprocess.CalledProcessError(1, "git")
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect
        path = self.wt.create("fix", 42)
        assert path == Path("/tmp/repo/.worktrees/fix-42")
        # The worktree add call (second call)
        cmd = mock_run.call_args_list[1][0][0]
        assert "worktree" in cmd
        assert "add" in cmd
        assert "-b" in cmd
        assert "fix/42" in cmd

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_create_existing_returns_path(self, mock_run, tmp_path):
        wt = WorktreeManager(tmp_path)
        wt_path = tmp_path / ".worktrees" / "fix-42"
        wt_path.mkdir(parents=True)
        path = wt.create("fix", 42)
        assert path == wt_path
        mock_run.assert_not_called()

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_remove(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert self.wt.remove("fix", 42) is True

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_remove_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert self.wt.remove("fix", 42) is False

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_push(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert self.wt.push("fix", 42) is True
        cmd = mock_run.call_args[0][0]
        assert "push" in cmd
        assert "fix/42" in cmd

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_push_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert self.wt.push("fix", 42) is False

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_list_worktrees(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=(
                "worktree /tmp/repo\nbranch refs/heads/main\n\n"
                "worktree /tmp/repo/.worktrees/fix-1\n"
                "branch refs/heads/fix/1\n"
            ),
            returncode=0,
        )
        result = self.wt.list_worktrees()
        assert len(result) == 2

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_create_existing_branch_no_worktree(self, mock_run):
        """Regression test for #38: create() should handle pre-existing branches."""
        def side_effect(cmd, **kwargs):
            # First call: rev-parse to check branch existence -> succeeds
            if "rev-parse" in cmd:
                return MagicMock(returncode=0)
            # Second call: worktree add (without -b) -> succeeds
            if "worktree" in cmd and "add" in cmd:
                assert "-b" not in cmd, "Should not use -b when branch exists"
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect
        path = self.wt.create("fix", 42)
        assert path == Path("/tmp/repo/.worktrees/fix-42")
        assert mock_run.call_count == 2

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_create_new_branch(self, mock_run):
        """When branch doesn't exist, create() should use -b flag."""
        def side_effect(cmd, **kwargs):
            # First call: rev-parse to check branch existence -> fails
            if "rev-parse" in cmd:
                raise subprocess.CalledProcessError(1, "git")
            # Second call: worktree add -b -> succeeds
            if "worktree" in cmd and "add" in cmd:
                assert "-b" in cmd, "Should use -b when branch is new"
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect
        path = self.wt.create("fix", 42)
        assert path == Path("/tmp/repo/.worktrees/fix-42")
        assert mock_run.call_count == 2

    @patch("wiz.coordination.worktree.subprocess.run")
    def test_list_worktrees_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert self.wt.list_worktrees() == []
