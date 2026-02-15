"""GitHub Issues coordination via gh CLI."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class GitHubIssues:
    """Manage GitHub issues via the gh CLI."""

    def __init__(
        self, repo: str, allowed_authors: list[str] | None = None,
    ) -> None:
        self.repo = repo
        self._ensured_labels: set[str] = set()
        self._allowed_authors: set[str] | None = (
            {a.lower() for a in allowed_authors} if allowed_authors else None
        )

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
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
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
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error("Failed to create issue: %s", e)
            return None

    def list_issues(
        self,
        labels: list[str] | None = None,
        state: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List issues with optional label and state filter.

        When allowed_authors is configured, issues from non-allowed authors
        are filtered out procedurally BEFORE returning, so their content
        never reaches agent prompts.
        """
        args = ["issue", "list", "--state", state, "--limit", str(limit), "--json",
                "number,title,labels,state,url,body,author"]
        if labels:
            for label in labels:
                args.extend(["--label", label])
        try:
            result = self._run_gh(args)
            issues = json.loads(result.stdout) if result.stdout.strip() else []
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return []

        return self._filter_by_author(issues)

    def _filter_by_author(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Procedurally filter issues to only those from allowed authors.

        This is a security boundary: it runs in Python code before issue
        content (title, body) ever reaches an agent prompt, preventing
        prompt injection via malicious GitHub issues.

        When allowed_authors is None (empty config), all issues pass through.
        """
        if not self._allowed_authors:
            return issues

        allowed: list[dict[str, Any]] = []
        for issue in issues:
            author = issue.get("author", {})
            login = (author.get("login") or "").lower()
            number = issue.get("number", "?")
            if login in self._allowed_authors:
                allowed.append(issue)
            else:
                logger.warning(
                    "Issue #%s rejected: author '%s' not in allowed list",
                    number, login,
                )
        return allowed

    def get_issue(self, issue_number: int) -> dict[str, Any] | None:
        """Get a single issue by number. Returns dict or None.

        Rejects issues from non-allowed authors when allowlist is configured.
        """
        try:
            result = self._run_gh(
                ["issue", "view", str(issue_number), "--json",
                 "number,title,labels,state,url,body,author"]
            )
            issue = json.loads(result.stdout) if result.stdout.strip() else None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return None

        if issue is None:
            return None

        filtered = self._filter_by_author([issue])
        return filtered[0] if filtered else None

    def add_comment(self, issue_number: int, body: str) -> bool:
        """Add a comment to an issue."""
        args = ["issue", "comment", str(issue_number), "--body", body]
        try:
            self._run_gh(args)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
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
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def close_issue(self, issue_number: int) -> bool:
        """Close an issue."""
        try:
            self._run_gh(["issue", "close", str(issue_number)])
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def reopen_issue(self, issue_number: int) -> bool:
        """Reopen an issue."""
        try:
            self._run_gh(["issue", "reopen", str(issue_number)])
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def check_duplicate(self, title: str) -> bool:
        """Check if an issue with similar title exists."""
        issues = self.list_issues()
        title_lower = title.lower()
        for issue in issues:
            if issue.get("title", "").lower() == title_lower:
                return True
        return False
