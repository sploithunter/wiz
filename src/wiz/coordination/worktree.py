"""Git worktree manager."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Manage git worktrees for isolated agent work."""

    def __init__(self, repo_path: Path, base_dir: str = ".worktrees") -> None:
        self.repo_path = Path(repo_path)
        self.base_dir = base_dir

    def _worktree_path(self, agent_type: str, issue: int | str) -> Path:
        return self.repo_path / self.base_dir / f"{agent_type}-{issue}"

    def _branch_name(self, agent_type: str, issue: int | str) -> str:
        return f"{agent_type}/{issue}"

    def _run_git(
        self, args: list[str], cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["git"] + args
        return subprocess.run(
            cmd,
            cwd=cwd or self.repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )

    def _branch_exists(self, branch: str) -> bool:
        """Check whether a local branch already exists."""
        try:
            self._run_git(["rev-parse", "--verify", f"refs/heads/{branch}"])
            return True
        except subprocess.CalledProcessError:
            return False

    def create(self, agent_type: str, issue: int | str) -> Path:
        """Create a worktree. Returns the worktree path."""
        wt_path = self._worktree_path(agent_type, issue)
        branch = self._branch_name(agent_type, issue)

        if wt_path.exists():
            return wt_path

        wt_path.parent.mkdir(parents=True, exist_ok=True)
        if self._branch_exists(branch):
            self._run_git(["worktree", "add", str(wt_path), branch])
        else:
            self._run_git(["worktree", "add", "-b", branch, str(wt_path)])
        logger.info("Created worktree: %s (branch: %s)", wt_path, branch)
        return wt_path

    def remove(self, agent_type: str, issue: int | str) -> bool:
        """Remove a worktree."""
        wt_path = self._worktree_path(agent_type, issue)
        branch = self._branch_name(agent_type, issue)
        try:
            self._run_git(["worktree", "remove", str(wt_path), "--force"])
            # Try to delete the branch too
            try:
                self._run_git(["branch", "-D", branch])
            except subprocess.CalledProcessError:
                pass  # Branch may already be deleted
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("Failed to remove worktree %s: %s", wt_path, e)
            return False

    def push(self, agent_type: str, issue: int | str) -> bool:
        """Push the worktree's branch to origin."""
        wt_path = self._worktree_path(agent_type, issue)
        branch = self._branch_name(agent_type, issue)
        try:
            self._run_git(["push", "-u", "origin", branch], cwd=wt_path)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error("Failed to push branch %s: %s", branch, e)
            return False

    def list_worktrees(self) -> list[dict[str, str]]:
        """List all worktrees."""
        try:
            result = self._run_git(["worktree", "list", "--porcelain"])
            worktrees = []
            current: dict[str, str] = {}
            for line in result.stdout.splitlines():
                if line.startswith("worktree "):
                    if current:
                        worktrees.append(current)
                    current = {"path": line.split(" ", 1)[1]}
                elif line.startswith("branch "):
                    current["branch"] = line.split(" ", 1)[1]
                elif line == "":
                    if current:
                        worktrees.append(current)
                    current = {}
            if current:
                worktrees.append(current)
            return worktrees
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

    def cleanup_stale(self, stale_days: int = 7) -> int:
        """Remove worktrees not modified in stale_days. Returns count removed."""
        import time

        removed = 0
        base = self.repo_path / self.base_dir
        if not base.exists():
            return 0

        cutoff = time.time() - (stale_days * 86400)
        for wt_dir in base.iterdir():
            if wt_dir.is_dir() and wt_dir.stat().st_mtime < cutoff:
                try:
                    self._run_git(["worktree", "remove", str(wt_dir), "--force"])
                    removed += 1
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    pass
        return removed

    def cleanup_merged(self, base_branch: str = "main") -> int:
        """Remove worktrees whose branches have been merged. Returns count removed."""
        removed = 0
        try:
            result = self._run_git(["branch", "--merged", base_branch])
            merged = {b.strip() for b in result.stdout.splitlines()}
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return 0

        base = self.repo_path / self.base_dir
        if not base.exists():
            return 0

        for wt_dir in base.iterdir():
            if not wt_dir.is_dir():
                continue
            # Infer branch from directory name
            parts = wt_dir.name.split("-", 1)
            if len(parts) == 2:
                branch = f"refs/heads/{parts[0]}/{parts[1]}"
                if branch in merged or f"{parts[0]}/{parts[1]}" in merged:
                    try:
                        self._run_git(["worktree", "remove", str(wt_dir), "--force"])
                        removed += 1
                    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                        pass
        return removed
