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

    def _run_gh(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = ["gh"] + args + ["-R", self.repo]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> str | None:
        """Create a PR. Returns PR URL or None."""
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
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
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
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return []

    def get_pr(self, pr_number: int) -> dict[str, Any] | None:
        """Get PR details."""
        args = [
            "pr", "view", str(pr_number),
            "--json", "number,title,state,url,body,headRefName,files",
        ]
        try:
            result = self._run_gh(args)
            return json.loads(result.stdout) if result.stdout.strip() else None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return None
