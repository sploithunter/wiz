"""Feature Proposer agent: proposes and implements features."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import FeatureProposerConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.coordination.worktree import WorktreeManager
from wiz.notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = (
    Path(__file__).parent.parent.parent.parent / "agents" / "feature-proposer" / "CLAUDE.md"
)


class FeatureProposerAgent(BaseAgent):
    agent_type = "claude"
    agent_name = "feature-proposer"

    def __init__(
        self,
        runner: SessionRunner,
        config: FeatureProposerConfig,
        github: GitHubIssues,
        worktree: WorktreeManager,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        super().__init__(runner, config)
        self.fp_config = config
        self.github = github
        self.worktree = worktree
        self.notifier = notifier

    def build_prompt(self, **kwargs: Any) -> str:
        mode = kwargs.get("mode", "propose")
        instructions = ""
        if CLAUDE_MD_PATH.exists():
            instructions = CLAUDE_MD_PATH.read_text()

        if mode == "propose":
            return f"""{instructions}

## Task: Propose Features
Analyze the codebase and propose ONE feature that would add the most value.
Create a GitHub issue with label `feature-candidate`.
Include: description, scope, acceptance criteria, estimated complexity.
"""
        else:
            issue = kwargs.get("issue", {})
            return f"""{instructions}

## Task: Implement Feature
Issue #{issue.get('number', 0)}: {issue.get('title', '')}

{issue.get('body', '')}

Implement this feature with full test coverage.
Commit all changes and ensure all tests pass.
"""

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        return {"success": result.success, "reason": result.reason, "mode": kwargs.get("mode")}

    def _notify_new_candidate(self, candidates: list[dict[str, Any]]) -> None:
        """Send Telegram notification for new feature candidates awaiting review."""
        if not self.notifier:
            return
        for issue in candidates:
            title = issue.get("title", "Untitled")
            url = issue.get("url", "")
            number = issue.get("number", "?")
            text = (
                f"*New Feature Candidate* \\#{number}\n"
                f"{title}\n"
                f"{url}\n\n"
                f"Add `feature-approved` label to implement."
            )
            self.notifier.send_message(text)

    def _auto_approve_candidates(self, candidates: list[dict[str, Any]]) -> None:
        """When require_approval=False, auto-promote candidates to approved."""
        for issue in candidates:
            number = issue.get("number", 0)
            self.github.update_labels(
                number,
                add=["feature-approved"],
                remove=["feature-candidate"],
            )
            logger.info("Auto-approved feature #%d (require_approval=False)", number)

    def run(self, cwd: str, timeout: float = 900, **kwargs: Any) -> dict[str, Any]:
        """Run feature proposer with full propose→approve→implement workflow.

        Logic:
        1. Check for feature-approved issues → implement the first one
        2. Check for feature-candidate issues:
           a. If require_approval=False → auto-approve them, then implement
           b. If require_approval=True → notify via Telegram, wait for human
        3. If no candidates and auto_propose_features → propose a new feature
        4. Otherwise → skip
        """
        if self.fp_config.features_per_run == 0:
            return {"skipped": True, "reason": "disabled"}

        # Check for approved features
        approved = self.github.list_issues(labels=["feature-approved"])

        if approved:
            # Implementation mode
            issue = approved[0]
            number = issue.get("number", 0)
            wt_path = self.worktree.create("feature", number)

            prompt = self.build_prompt(mode="implement", issue=issue)
            result = self.runner.run(
                name=f"wiz-feature-{number}",
                cwd=str(wt_path),
                prompt=prompt,
                agent=self.agent_type,
                model=self.fp_config.model or None,
                timeout=timeout,
                flags=self.fp_config.flags or None,
            )

            if result.success:
                pushed = self.worktree.push("feature", number)
                if pushed:
                    self.github.update_labels(
                        number,
                        add=["feature-implemented"],
                        remove=["feature-approved"],
                    )
                else:
                    logger.error("Push failed for feature #%d; keeping feature-approved label", number)
                    return {"success": False, "reason": "push_failed", "mode": "implement"}

            return self.process_result(result, mode="implement")

        # Check for candidates awaiting approval
        candidates = self.github.list_issues(labels=["feature-candidate"])

        if candidates and not self.fp_config.require_approval:
            # Auto-approve and implement immediately
            self._auto_approve_candidates(candidates)
            issue = candidates[0]
            number = issue.get("number", 0)
            wt_path = self.worktree.create("feature", number)

            prompt = self.build_prompt(mode="implement", issue=issue)
            result = self.runner.run(
                name=f"wiz-feature-{number}",
                cwd=str(wt_path),
                prompt=prompt,
                agent=self.agent_type,
                model=self.fp_config.model or None,
                timeout=timeout,
                flags=self.fp_config.flags or None,
            )

            if result.success:
                pushed = self.worktree.push("feature", number)
                if pushed:
                    self.github.update_labels(
                        number,
                        add=["feature-implemented"],
                        remove=["feature-approved"],
                    )
                else:
                    logger.error("Push failed for feature #%d; keeping feature-approved label", number)
                    return {"success": False, "reason": "push_failed", "mode": "implement"}

            return self.process_result(result, mode="implement")

        if candidates:
            # Candidates exist but require human approval — notify and wait
            self._notify_new_candidate(candidates)
            return {"skipped": True, "reason": "awaiting_approval",
                    "candidates": len(candidates)}

        if self.fp_config.auto_propose_features:
            # No candidates at all — propose a new feature
            prompt = self.build_prompt(mode="propose")
            result = self.runner.run(
                name="wiz-feature-propose",
                cwd=cwd,
                prompt=prompt,
                agent=self.agent_type,
                model=self.fp_config.model or None,
                timeout=timeout,
                flags=self.fp_config.flags or None,
            )

            # Notify about new candidates after proposing
            if result.success:
                new_candidates = self.github.list_issues(labels=["feature-candidate"])
                if new_candidates:
                    self._notify_new_candidate(new_candidates)

            return self.process_result(result, mode="propose")

        return {"skipped": True, "reason": "no_approved_features"}
