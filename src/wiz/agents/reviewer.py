"""Reviewer agent: reviews bug fixes and creates PRs or sends back."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import ReviewerConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.github_prs import GitHubPRs
from wiz.coordination.loop_tracker import LoopTracker
from wiz.notifications.telegram import TelegramNotifier

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
    ) -> None:
        super().__init__(runner, config)
        self.reviewer_config = config
        self.github = github
        self.prs = prs
        self.loop_tracker = loop_tracker
        self.notifier = notifier
        self.repo_name = repo_name

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

            # Run review session
            prompt = self.build_prompt(issue=issue, branch=branch)
            result = self.runner.run(
                name=f"wiz-reviewer-{number}",
                cwd=cwd,
                prompt=prompt,
                agent=self.agent_type,
                timeout=timeout,
            )

            if not result.success:
                results.append({"issue": number, "action": "error", "reason": result.reason})
                continue

            # Check events/output for APPROVED/REJECTED
            # In practice, we'd parse the agent's output. For now, simulate based on success.
            approved = self._check_approval(result)

            if approved:
                # Create PR
                pr_url = self.prs.create_pr(
                    title=f"fix: {issue.get('title', 'Bug fix')}",
                    body=f"Fixes #{number}\n\nReviewed and approved by Wiz Reviewer.",
                    head=branch,
                )
                self.github.close_issue(number)
                results.append({"issue": number, "action": "approved", "pr": pr_url})
            else:
                # Reject: send back with feedback
                cycle = self.loop_tracker.record_cycle(number, "Review rejected")
                self.github.add_comment(number, "Review rejected: fix needs improvement")
                self.github.update_labels(
                    number, add=["needs-fix"], remove=["needs-review"]
                )

                if self.loop_tracker.is_max_reached(number):
                    self._escalate(number, issue.get("title", ""))
                    results.append({"issue": number, "action": "escalated", "cycle": cycle})
                else:
                    results.append({"issue": number, "action": "rejected", "cycle": cycle})

        return {"reviews": len(results), "results": results}

    def _check_approval(self, result: SessionResult) -> bool:
        """Check if the review approved the fix. Simplified heuristic."""
        # In real implementation, parse agent output for APPROVED/REJECTED
        # For now, assume approved if session completed successfully
        for event in result.events:
            data = event.get("data", {})
            response = data.get("response", "")
            if "APPROVED" in response.upper():
                return True
            if "REJECTED" in response.upper():
                return False
        return result.success

    def _escalate(self, issue_number: int, title: str) -> None:
        """Escalate an issue to human review."""
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
