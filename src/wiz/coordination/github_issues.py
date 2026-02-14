"""GitHub Issues coordination via gh CLI."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class GitHubIssues:
    """Manage GitHub issues via the gh CLI."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self._ensured_labels: set[str] = set()

    def _run_gh(
        self, args: list[str], check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["gh"] + args + ["-R", self.repo]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    def ensure_labels(self, labels: list[str]) -> None:
        """Create labels on the repo if they don't exist."""
        for label in labels:
            if label in self._ensured_labels:
                continue
            try:
                subprocess.run(
                    ["gh", "label", "create", label,
                     "-R", self.repo, "--force"],
                    capture_output=True, text=True,
                    check=True, timeout=15,
                )
                self._ensured_labels.add(label)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.warning("Could not ensure label %r exists", label)

    def create_issue(
        self, title: str, body: str,
        labels: list[str] | None = None,
    ) -> str | None:
        """Create an issue. Returns issue URL or None."""
        if labels:
            self.ensure_labels(labels)
        args = ["issue", "create", "--title", title, "--body", body]
        if labels:
            args.extend(["--label", ",".join(labels)])
        try:
            result = self._run_gh(args)
            return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error("Failed to create issue: %s", e)
            return None

    def list_issues(
        self,
        labels: list[str] | None = None,
        state: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List issues with optional label and state filter."""
        args = ["issue", "list", "--state", state, "--limit", str(limit), "--json",
                "number,title,labels,state,url,body"]
        if labels:
            for label in labels:
                args.extend(["--label", label])
        try:
            result = self._run_gh(args)
            return json.loads(result.stdout) if result.stdout.strip() else []
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return []

    def get_issue(self, issue_number: int) -> dict[str, Any] | None:
        """Get a single issue by number. Returns dict or None."""
        try:
            result = self._run_gh(
                ["issue", "view", str(issue_number), "--json",
                 "number,title,labels,state,url,body"]
            )
            return json.loads(result.stdout) if result.stdout.strip() else None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return None

    def add_comment(self, issue_number: int, body: str) -> bool:
        """Add a comment to an issue."""
        args = ["issue", "comment", str(issue_number), "--body", body]
        try:
            self._run_gh(args)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def update_labels(
        self,
        issue_number: int,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> bool:
        """Add or remove labels from an issue."""
        try:
            if add:
                self.ensure_labels(add)
                self._run_gh(
                    ["issue", "edit", str(issue_number),
                     "--add-label", ",".join(add)]
                )
            if remove:
                self._run_gh(
                    ["issue", "edit", str(issue_number), "--remove-label", ",".join(remove)]
                )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def close_issue(self, issue_number: int) -> bool:
        """Close an issue."""
        try:
            self._run_gh(["issue", "close", str(issue_number)])
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def reopen_issue(self, issue_number: int) -> bool:
        """Reopen an issue."""
        try:
            self._run_gh(["issue", "reopen", str(issue_number)])
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def check_duplicate(self, title: str) -> bool:
        """Check if an issue with similar title exists."""
        issues = self.list_issues()
        title_lower = title.lower()
        for issue in issues:
            if issue.get("title", "").lower() == title_lower:
                return True
        return False
