"""Reviewer agent: reviews bug fixes and creates PRs or sends back."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import ReviewerConfig
from wiz.coordination.distributed_lock import DistributedLockManager
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.github_prs import GitHubPRs
from wiz.coordination.loop_tracker import LoopTracker
from wiz.notifications.telegram import TelegramNotifier
from wiz.orchestrator.self_improve import SelfImprovementGuard

logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = Path(__file__).parent.parent.parent.parent / "agents" / "reviewer" / "CLAUDE.md"


class ReviewerAgent(BaseAgent):
    agent_type = "codex"
    agent_name = "reviewer"

    def __init__(
        self,
        runner: SessionRunner,
        config: ReviewerConfig,
        github: GitHubIssues,
        prs: GitHubPRs,
        loop_tracker: LoopTracker,
        notifier: TelegramNotifier,
        repo_name: str = "",
        distributed_locks: DistributedLockManager | None = None,
        self_improve: bool = False,
    ) -> None:
        super().__init__(runner, config)
        self.reviewer_config = config
        self.github = github
        self.prs = prs
        self.loop_tracker = loop_tracker
        self.notifier = notifier
        self.repo_name = repo_name
        self.distributed_locks = distributed_locks
        self.self_improve = self_improve
        self.guard = SelfImprovementGuard() if self_improve else None

    def build_prompt(self, **kwargs: Any) -> str:
        """Build review prompt for a specific issue."""
        issue = kwargs.get("issue", {})
        instructions = ""
        if CLAUDE_MD_PATH.exists():
            instructions = CLAUDE_MD_PATH.read_text()

        title = issue.get("title", "Unknown")
        body = issue.get("body", "No description")
        number = issue.get("number", 0)
        branch = kwargs.get("branch", f"fix/{number}")

        return f"""{instructions}

## Issue #{number}: {title}

{body}

## Branch to Review: {branch}

## Task
1. Check out the fix branch and review the changes
2. Verify the fix addresses the root cause (not just symptoms)
3. Check that regression tests exist and are meaningful
4. Look for new issues introduced by the fix
5. Consider edge cases

If the fix is adequate:
- Output: APPROVED

If the fix is inadequate:
- Output: REJECTED
- Provide specific, actionable feedback
"""

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        """Process review result - simplified, real logic is in run()."""
        return {"success": result.success, "reason": result.reason}

    def run(self, cwd: str, timeout: float = 300, **kwargs: Any) -> dict[str, Any]:
        """Review each needs-review issue."""
        issues = kwargs.get("issues", [])
        if not issues:
            issues = self.github.list_issues(labels=["needs-review"])

        # Pre-filter issues already claimed by another machine
        if self.distributed_locks:
            issues = [
                i for i in issues if not self.distributed_locks.is_claimed(i)
            ]

        issues = issues[: self.reviewer_config.max_reviews_per_run]
        results: list[dict[str, Any]] = []

        for issue in issues:
            number = issue.get("number", 0)
            branch = f"fix/{number}"

            # Check if max cycles reached before even reviewing
            if self.loop_tracker.is_max_reached(number):
                self._escalate(number, issue.get("title", ""))
                results.append({"issue": number, "action": "escalated"})
                continue

            # Try distributed lock
            if self.distributed_locks and not self.distributed_locks.acquire(number):
                logger.info("Issue #%d claimed by another machine, skipping review", number)
                results.append({"issue": number, "action": "skipped", "reason": "distributed-locked"})
                continue

            try:
                # Run review session
                prompt = self.build_prompt(issue=issue, branch=branch)
                result = self.runner.run(
                    name=f"wiz-reviewer-{number}",
                    cwd=cwd,
                    prompt=prompt,
                    agent=self.agent_type,
                    model=self.reviewer_config.model,
                    timeout=timeout,
                    flags=self.reviewer_config.flags or None,
                )

                if not result.success:
                    results.append({"issue": number, "action": "error", "reason": result.reason})
                    continue

                # Check events/output for APPROVED/REJECTED
                approved, feedback = self._check_approval(result)
                logger.info(
                    "Issue #%d review verdict: %s",
                    number, "APPROVED" if approved else "REJECTED",
                )

                if approved:
                    # Guard: don't create PR for empty branches
                    changed_files = self._get_branch_files(branch)
                    if not changed_files:
                        logger.warning(
                            "Issue #%d: branch %s has no changes, skipping PR",
                            number, branch,
                        )
                        self.github.update_labels(
                            number, add=["needs-fix"], remove=["needs-review"]
                        )
                        results.append({
                            "issue": number, "action": "rejected",
                            "reason": "empty-branch",
                        })
                        continue

                    # Create PR
                    pr_url = self.prs.create_pr(
                        title=f"fix: {issue.get('title', 'Bug fix')}",
                        body=f"Fixes #{number}\n\nReviewed and approved by Wiz Reviewer.",
                        head=branch,
                    )

                    if not pr_url:
                        logger.error("Issue #%d: PR creation failed", number)
                        self.github.add_comment(
                            number, "Review approved but PR creation failed. Keeping issue open."
                        )
                        results.append({
                            "issue": number,
                            "action": "pr_failed",
                            "pr": None,
                        })
                        continue

                    # Check self-improvement guard for protected files
                    needs_human = False
                    if self.guard:
                        changed_files = self._get_branch_files(branch)
                        guard_result = self.guard.validate_changes(changed_files)
                        if guard_result["needs_human_review"]:
                            needs_human = True
                            self.github.update_labels(
                                number, add=["requires-human-review"],
                            )
                            self.notifier.notify_escalation(
                                self.repo_name,
                                f"#{number}: {issue.get('title', '')}",
                                f"Protected files changed: {', '.join(guard_result['protected_files'])}",
                            )
                            logger.info(
                                "Issue #%d: PR created but requires human review (protected files)",
                                number,
                            )

                    merged = False
                    if not needs_human:
                        # Auto-merge if enabled
                        if self.reviewer_config.auto_merge:
                            pr_number = self._extract_pr_number(pr_url)
                            if pr_number:
                                merged = self.prs.merge_pr(pr_number)
                                if merged:
                                    logger.info("Issue #%d: PR #%d merged", number, pr_number)
                                else:
                                    logger.warning("Issue #%d: PR #%d merge failed", number, pr_number)
                        self.github.close_issue(number)
                    results.append({
                        "issue": number,
                        "action": "approved",
                        "pr": pr_url,
                        "merged": merged,
                        "needs_human_review": needs_human,
                    })
                else:
                    # Reject: send back with feedback
                    cycle = self.loop_tracker.record_cycle(number, "Review rejected")
                    comment = self._build_rejection_comment(feedback)
                    self.github.add_comment(number, comment)
                    self.github.update_labels(
                        number, add=["needs-fix"], remove=["needs-review"]
                    )

                    if self.loop_tracker.is_max_reached(number):
                        self._escalate(number, issue.get("title", ""))
                        results.append({"issue": number, "action": "escalated", "cycle": cycle})
                    else:
                        results.append({"issue": number, "action": "rejected", "cycle": cycle})

            finally:
                if self.distributed_locks:
                    self.distributed_locks.release(number)

        return {"reviews": len(results), "results": results}

    def _check_approval(self, result: SessionResult) -> tuple[bool, str]:
        """Check if the review approved the fix.

        Returns (approved, feedback) where feedback is the reviewer's
        explanation text (useful for rejection comments on the issue).

        Strategy (in priority order):
        1. Look for structured JSON verdict: {"verdict": "approved"/"rejected"}
        2. Keyword scan: standalone APPROVED/REJECTED in output
        3. Fall back to result.success
        """
        all_text = self._collect_event_text(result)
        feedback = self._extract_feedback(all_text)

        # 1. Try structured JSON verdict
        verdict = self._parse_json_verdict(all_text)
        if verdict is not None:
            logger.debug("Verdict from JSON: %s", verdict)
            return verdict, feedback

        # 2. Keyword scan on events (more targeted than full text)
        for event in result.events:
            data = event.get("data", {})
            response = data.get("response", "")
            text = event.get("text", "")
            for chunk in (response, text):
                kw = self._keyword_verdict(chunk)
                if kw is not None:
                    return kw, feedback

        # 3. Keyword scan on full collected text
        kw = self._keyword_verdict(all_text)
        if kw is not None:
            logger.debug("Verdict from keyword scan: %s", kw)
            return kw, feedback

        # 4. Fallback
        logger.debug("No explicit verdict found, falling back to result.success=%s", result.success)
        return result.success, feedback

    @staticmethod
    def _collect_event_text(result: SessionResult) -> str:
        """Collect all text from result events, output, and reason."""
        chunks: list[str] = []
        # Include direct output (e.g. codex exec stdout)
        if result.output:
            chunks.append(result.output)
        for event in result.events:
            data = event.get("data", {})
            for key in ("response", "message"):
                val = data.get(key, "")
                if val:
                    chunks.append(val)
            text = event.get("text", "")
            if text:
                chunks.append(text)
        if result.reason:
            chunks.append(result.reason)
        return "\n".join(chunks)

    @staticmethod
    def _parse_json_verdict(text: str) -> bool | None:
        """Extract verdict from JSON blocks like ```json{"verdict":"approved"}```."""
        pattern = r"```json\s*(\{.*?\})\s*```"
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                obj = json.loads(match.group(1))
                if isinstance(obj, dict) and "verdict" in obj:
                    v = obj["verdict"].lower().strip()
                    if v in ("approved", "approve", "pass"):
                        return True
                    if v in ("rejected", "reject", "fail"):
                        return False
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    @staticmethod
    def _keyword_verdict(text: str) -> bool | None:
        """Scan for standalone APPROVED/REJECTED keywords.

        Uses word boundaries to avoid false positives like
        'the fix was not APPROVED by the standards'.
        """
        if not text:
            return None
        upper = text.upper()
        # Look for REJECTED first (explicit rejection takes priority)
        if re.search(r"\bREJECTED\b", upper):
            return False
        if re.search(r"\bAPPROVED\b", upper):
            return True
        return None

    @staticmethod
    def _extract_feedback(text: str) -> str:
        """Extract the reviewer's feedback/reasoning from the output text.

        Looks for text after REJECTED keyword, structured reason blocks,
        or falls back to the last substantial paragraph.
        """
        if not text:
            return ""

        # 1. Try structured JSON feedback: {"verdict": "rejected", "reason": "..."}
        pattern = r"```json\s*(\{.*?\})\s*```"
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                obj = json.loads(match.group(1))
                if isinstance(obj, dict):
                    reason = obj.get("reason", obj.get("feedback", ""))
                    if reason:
                        return reason.strip()
            except (json.JSONDecodeError, AttributeError):
                continue

        # 2. Look for text after "REJECTED" keyword
        rejected_match = re.search(
            r"\bREJECTED\b[:\s]*(.+)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if rejected_match:
            after = rejected_match.group(1).strip()
            # Take up to ~1000 chars of feedback
            if after:
                return after[:1000].strip()

        # 3. Look for "Reason:" or "Suggestions:" blocks
        reason_match = re.search(
            r"(?:Reason|Suggestions?|Feedback|Issues?)[:\s]*(.+)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if reason_match:
            return reason_match.group(1)[:1000].strip()

        return ""

    @staticmethod
    def _build_rejection_comment(feedback: str) -> str:
        """Build a GitHub comment for a rejection with reviewer feedback."""
        if not feedback:
            return (
                "**Review: REJECTED**\n\n"
                "The reviewer did not provide specific feedback. "
                "Please check the branch for test failures and ensure "
                "all tests pass before resubmitting."
            )
        return f"**Review: REJECTED**\n\n{feedback}"

    @staticmethod
    def _extract_pr_number(pr_url: str) -> int | None:
        """Extract PR number from a GitHub PR URL."""
        match = re.search(r"/pull/(\d+)", pr_url)
        return int(match.group(1)) if match else None

    def _get_branch_files(self, branch: str) -> list[str]:
        """Get list of files changed in the branch vs main."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"main...{branch}"],
                capture_output=True, text=True, check=True, timeout=10,
            )
            return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            logger.debug("Could not get branch files for %s", branch)
            return []

    def _escalate(self, issue_number: int, title: str) -> None:
        """Escalate an issue to human review."""
        logger.warning("Escalating issue #%d (%s): max review cycles reached", issue_number, title)
        self.github.update_labels(
            issue_number,
            add=["escalated-to-human"],
            remove=["needs-review", "needs-fix"],
        )
        self.github.add_comment(
            issue_number,
            f"Escalated to human: max review cycles "
            f"({self.reviewer_config.max_review_cycles}) reached.",
        )
        self.notifier.notify_escalation(
            self.repo_name,
            f"#{issue_number}: {title}",
            f"Max review cycles ({self.reviewer_config.max_review_cycles}) reached",
        )
