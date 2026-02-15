"""Bug Fixer agent: fixes bugs from GitHub issues."""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BugFixerConfig
from wiz.coordination.distributed_lock import DistributedLockManager
from wiz.coordination.file_lock import FileLockManager
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.stagnation import StagnationDetector
from wiz.coordination.worktree import WorktreeManager

logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = Path(__file__).parent.parent.parent.parent / "agents" / "bug-fixer" / "CLAUDE.md"

# Priority ordering for issues
PRIORITY_ORDER = ["P0", "P1", "P2", "P3", "P4"]


def _check_files_changed(work_dir: str) -> bool:
    """Check if the branch has any changes vs main (committed or uncommitted)."""
    try:
        # First check uncommitted changes against HEAD
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout.strip():
            return True

        # Then check committed changes vs the base branch (main)
        # This catches the case where Claude Code already committed the fix
        for base in ("main", "master"):
            result = subprocess.run(
                ["git", "log", "--oneline", f"{base}..HEAD"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return True

        return False
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        logger.debug("Could not check git diff in %s", work_dir)
        return False


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
        distributed_locks: DistributedLockManager | None = None,
        parallel: bool = False,
    ) -> None:
        super().__init__(runner, config)
        self.fixer_config = config
        self.github = github
        self.worktree = worktree
        self.locks = locks
        self.distributed_locks = distributed_locks
        self.parallel = parallel

    def build_prompt(self, **kwargs: Any) -> str:
        """Build fix prompt for a specific issue."""
        issue = kwargs.get("issue", {})
        instructions = ""
        if CLAUDE_MD_PATH.exists():
            instructions = CLAUDE_MD_PATH.read_text()

        title = issue.get("title", "Unknown")
        body = issue.get("body", "No description")
        number = issue.get("number", 0)

        # Check if this is a retry (needs-fix label = sent back from reviewer)
        reviewer_feedback = self._get_reviewer_feedback(issue)

        prompt = f"""{instructions}

## Issue #{number}: {title}

{body}
"""
        if reviewer_feedback:
            prompt += f"""
## Previous Review Feedback
The reviewer rejected the previous fix attempt. You MUST address the following feedback:

{reviewer_feedback}

Pay close attention to this feedback. The fix was rejected for specific reasons — do not repeat the same mistakes.
"""

        prompt += f"""
## Task
1. Read the issue and understand the bug
2. Implement a fix
3. Write a regression test that fails without the fix and passes with it
4. Run the full test suite to ensure no regressions
5. Commit all changes with a descriptive message referencing issue #{number}
"""
        return prompt

    def _get_reviewer_feedback(self, issue: dict) -> str:
        """Extract reviewer feedback from issue comments if this is a retry.

        Only returns feedback when the issue has a needs-fix label,
        indicating it was sent back from review.
        """
        labels = issue.get("labels", [])
        label_names = {
            (l.get("name", "") if isinstance(l, dict) else str(l)).lower()
            for l in labels
        }
        if "needs-fix" not in label_names:
            return ""

        number = issue.get("number", 0)
        if not number:
            return ""

        try:
            comments = self.github.get_comments(number, last_n=3)
            # Find the most recent review rejection comment
            for comment in reversed(comments):
                body = comment.get("body", "")
                if "Review: REJECTED" in body or "Review rejected" in body:
                    return body
            return ""
        except Exception:
            logger.debug("Could not fetch reviewer feedback for issue #%d", number)
            return ""

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        """Process fix result."""
        return {
            "success": result.success,
            "reason": result.reason,
            "elapsed": result.elapsed,
            "issue": kwargs.get("issue", {}),
        }

    def _process_issue(
        self, issue: dict, cwd: str, timeout: float
    ) -> dict[str, Any]:
        """Process a single issue: acquire locks, fix in worktree, push."""
        number = issue.get("number", 0)
        title = issue.get("title", "")
        owner = "bug-fixer"
        logger.info("Fixing issue #%d: %s", number, title)
        stagnation = StagnationDetector(limit=self.fixer_config.stagnation_limit)

        # Try distributed lock first
        if self.distributed_locks and not self.distributed_locks.acquire(number):
            logger.info("Issue #%d claimed by another machine, skipping", number)
            return {"issue": number, "skipped": True, "reason": "distributed-locked"}

        # Try to acquire local file lock
        lock_key = f"issue-{number}"
        if self.locks and not self.locks.acquire(lock_key, owner):
            logger.info("Issue #%d locked, skipping", number)
            if self.distributed_locks:
                self.distributed_locks.release(number)
            return {"issue": number, "skipped": True, "reason": "locked"}

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
                flags=self.fixer_config.flags or None,
            )

            if result.success:
                files_changed = _check_files_changed(work_dir)
                if stagnation.check(files_changed=files_changed):
                    logger.warning("Issue #%d: stagnation detected", number)
                    self.github.add_comment(
                        number, "Fix stalled: no progress after multiple attempts"
                    )
                    self.github.update_labels(
                        number, add=["fix-stalled"], remove=["needs-fix"]
                    )
                    return {"issue": number, "stalled": True}
                elif not files_changed:
                    logger.warning("Issue #%d: session completed but no files changed", number)
                    return {"issue": number, "fixed": False, "reason": "no-changes"}
                else:
                    if self.worktree:
                        pushed = self.worktree.push("fix", number)
                        if not pushed:
                            logger.error(
                                "Issue #%d: push failed for fix/%d", number, number
                            )
                            self.github.add_comment(
                                number,
                                "Fix applied locally but push failed — retaining labels for retry",
                            )
                            return {"issue": number, "failed": True, "reason": "push-failed"}
                    logger.info("Issue #%d: fix applied, pushed to fix/%d", number, number)
                    self.github.add_comment(number, "Fix applied, ready for review")
                    self.github.update_labels(
                        number, add=["needs-review"], remove=["needs-fix", "wiz-bug"]
                    )
                    return {"issue": number, "fixed": True}
            else:
                logger.warning("Issue #%d: fix failed: %s", number, result.reason)
                return {"issue": number, "failed": True, "reason": result.reason}

        finally:
            if self.distributed_locks:
                self.distributed_locks.release(number)
            if self.locks:
                self.locks.release(lock_key, owner)

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

        # Pre-filter issues already claimed by another machine
        if self.distributed_locks:
            issues = [
                i for i in issues if not self.distributed_locks.is_claimed(i)
            ]

        # Sort by priority (P0 first)
        issues.sort(key=_extract_priority)

        # Limit to max_fixes_per_run
        issues = issues[: self.fixer_config.max_fixes_per_run]

        if self.parallel and len(issues) > 1:
            results = self._run_parallel(issues, cwd, timeout)
        else:
            results = [self._process_issue(i, cwd, timeout) for i in issues]

        return {"issues_processed": len(results), "results": results}

    def _run_parallel(
        self, issues: list[dict], cwd: str, timeout: float,
    ) -> list[dict[str, Any]]:
        """Process issues concurrently using ThreadPoolExecutor."""
        results: list[dict[str, Any]] = []
        max_workers = min(len(issues), self.fixer_config.max_fixes_per_run)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_issue = {
                executor.submit(self._process_issue, issue, cwd, timeout): issue
                for issue in issues
            }
            for future in as_completed(future_to_issue):
                issue = future_to_issue[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    number = issue.get("number", 0)
                    logger.error("Issue #%d: parallel fix error: %s", number, e)
                    results.append({"issue": number, "failed": True, "reason": str(e)})

        return results
