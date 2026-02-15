"""GitHub Pull Requests coordination via gh CLI."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class GitHubPRs:
    """Manage GitHub PRs via the gh CLI."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self._default_branch: str | None = None

    def _run_gh(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = ["gh"] + args + ["-R", self.repo]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    def get_default_branch(self) -> str:
        """Return the repository's default branch, cached after first call."""
        if self._default_branch is not None:
            return self._default_branch
        try:
            result = self._run_gh([
                "repo", "view",
                "--json", "defaultBranchRef",
                "-q", ".defaultBranchRef.name",
            ])
            branch = result.stdout.strip()
            if branch:
                self._default_branch = branch
                return branch
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            logger.debug("Could not detect default branch for %s, falling back to 'main'", self.repo)
        return "main"

    def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str | None = None,
    ) -> str | None:
        """Create a PR. Returns PR URL or None."""
        if base is None:
            base = self.get_default_branch()
        args = [
            "pr", "create",
            "--title", title,
            "--body", body,
            "--head", head,
            "--base", base,
        ]
        try:
            result = self._run_gh(args)
            return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error("Failed to create PR: %s", e)
            return None

    def list_prs(self, state: str = "open", limit: int = 50) -> list[dict[str, Any]]:
        """List PRs."""
        args = [
            "pr", "list",
            "--state", state,
            "--limit", str(limit),
            "--json", "number,title,state,url,headRefName",
        ]
        try:
            result = self._run_gh(args)
            return json.loads(result.stdout) if result.stdout.strip() else []
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return []

    def merge_pr(
        self,
        pr_number: int,
        method: str = "squash",
        delete_branch: bool = True,
    ) -> bool:
        """Merge a PR. Returns True on success."""
        args = [
            "pr", "merge", str(pr_number),
            f"--{method}",
        ]
        if delete_branch:
            args.append("--delete-branch")
        try:
            self._run_gh(args)
            logger.info("Merged PR #%d (%s)", pr_number, method)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error("Failed to merge PR #%d: %s", pr_number, e)
            return False

    def get_pr(self, pr_number: int) -> dict[str, Any] | None:
        """Get PR details."""
        args = [
            "pr", "view", str(pr_number),
            "--json", "number,title,state,url,body,headRefName,files",
        ]
        try:
            result = self._run_gh(args)
            return json.loads(result.stdout) if result.stdout.strip() else None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return None
