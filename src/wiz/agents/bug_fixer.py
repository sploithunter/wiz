"""Bug Fixer agent: fixes bugs from GitHub issues."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BugFixerConfig
from wiz.coordination.file_lock import FileLockManager
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.strikes import StrikeTracker
from wiz.coordination.worktree import WorktreeManager

logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = Path(__file__).parent.parent.parent.parent / "agents" / "bug-fixer" / "CLAUDE.md"

# Priority ordering for issues
PRIORITY_ORDER = ["P0", "P1", "P2", "P3", "P4"]


def _extract_priority(issue: dict) -> int:
    """Extract priority from issue title like '[P2] description'. Lower = higher priority."""
    title = issue.get("title", "")
    for i, p in enumerate(PRIORITY_ORDER):
        if f"[{p}]" in title:
            return i
    return len(PRIORITY_ORDER)


class BugFixerAgent(BaseAgent):
    agent_type = "claude"
    agent_name = "bug-fixer"

    def __init__(
        self,
        runner: SessionRunner,
        config: BugFixerConfig,
        github: GitHubIssues,
        worktree: WorktreeManager,
        locks: FileLockManager,
        strikes: StrikeTracker | None = None,
    ) -> None:
        super().__init__(runner, config)
        self.fixer_config = config
        self.github = github
        self.worktree = worktree
        self.locks = locks
        self.strikes = strikes

    def build_prompt(self, **kwargs: Any) -> str:
        """Build fix prompt for a specific issue."""
        issue = kwargs.get("issue", {})
        instructions = ""
        if CLAUDE_MD_PATH.exists():
            instructions = CLAUDE_MD_PATH.read_text()

        title = issue.get("title", "Unknown")
        body = issue.get("body", "No description")
        number = issue.get("number", 0)

        return f"""{instructions}

## Issue #{number}: {title}

{body}

## Task
1. Read the issue and understand the bug
2. Implement a fix
3. Write a regression test that fails without the fix and passes with it
4. Run the full test suite to ensure no regressions
5. Commit all changes with a descriptive message referencing issue #{number}
"""

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        """Process fix result."""
        return {
            "success": result.success,
            "reason": result.reason,
            "elapsed": result.elapsed,
            "issue": kwargs.get("issue", {}),
        }

    def run(self, cwd: str, timeout: float = 600, **kwargs: Any) -> dict[str, Any]:
        """Override run to process multiple issues with worktrees and locks."""
        issues = kwargs.get("issues", [])
        if not issues:
            # Pick up new bugs (wiz-bug) and issues sent back from review (needs-fix)
            issues = self.github.list_issues(labels=["wiz-bug"])
            issues += self.github.list_issues(labels=["needs-fix"])
            # Deduplicate by issue number
            seen = set()
            unique = []
            for issue in issues:
                num = issue.get("number")
                if num not in seen:
                    seen.add(num)
                    unique.append(issue)
            issues = unique

        # Sort by priority (P0 first)
        issues.sort(key=_extract_priority)

        # Limit to max_fixes_per_run
        issues = issues[: self.fixer_config.max_fixes_per_run]

        results: list[dict[str, Any]] = []
        owner = "bug-fixer"

        for issue in issues:
            number = issue.get("number", 0)

            # Check persistent stagnation before attempting fix
            if self.strikes and self.strikes.is_escalated(
                number, max_strikes=self.fixer_config.stagnation_limit
            ):
                logger.info("Issue #%d already stalled, skipping", number)
                results.append({"issue": number, "skipped": True, "reason": "stalled"})
                continue

            # Try to acquire locks if available
            lock_key = f"issue-{number}"
            if self.locks and not self.locks.acquire(lock_key, owner):
                logger.info("Issue #%d locked, skipping", number)
                results.append({"issue": number, "skipped": True, "reason": "locked"})
                continue

            try:
                # Create worktree if available, otherwise work in main dir
                if self.worktree:
                    work_dir = str(self.worktree.create("fix", number))
                else:
                    work_dir = cwd

                # Build and run
                prompt = self.build_prompt(issue=issue)
                result = self.runner.run(
                    name=f"wiz-bug-fixer-{number}",
                    cwd=work_dir,
                    prompt=prompt,
                    agent=self.agent_type,
                    timeout=timeout,
                )

                if result.success:
                    if self.worktree:
                        self.worktree.push("fix", number)
                    self.github.add_comment(number, "Fix applied, ready for review")
                    self.github.update_labels(
                        number, add=["needs-review"], remove=["needs-fix", "wiz-bug"]
                    )
                    results.append({"issue": number, "fixed": True})
                else:
                    # Record failed attempt as a strike
                    if self.strikes:
                        strike_count = self.strikes.record_issue_strike(
                            number, result.reason or "failed"
                        )
                        if strike_count >= self.fixer_config.stagnation_limit:
                            self.github.add_comment(
                                number,
                                "Fix stalled: no progress after multiple attempts",
                            )
                            self.github.update_labels(
                                number, add=["fix-stalled"], remove=["needs-fix"]
                            )
                            results.append({"issue": number, "stalled": True})
                            continue
                    results.append({"issue": number, "failed": True, "reason": result.reason})

            finally:
                if self.locks:
                    self.locks.release(lock_key, owner)

        return {"issues_processed": len(results), "results": results}
