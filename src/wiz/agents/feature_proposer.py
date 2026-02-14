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
    ) -> None:
        super().__init__(runner, config)
        self.fp_config = config
        self.github = github
        self.worktree = worktree

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

    def run(self, cwd: str, timeout: float = 900, **kwargs: Any) -> dict[str, Any]:
        """Run feature proposer with conditional logic."""
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
                timeout=timeout,
            )

            if result.success:
                self.worktree.push("feature", number)

            return self.process_result(result, mode="implement")

        elif self.fp_config.auto_propose_features:
            # Check if backlog is empty
            candidates = self.github.list_issues(labels=["feature-candidate"])
            if not candidates:
                prompt = self.build_prompt(mode="propose")
                result = self.runner.run(
                    name="wiz-feature-propose",
                    cwd=cwd,
                    prompt=prompt,
                    agent=self.agent_type,
                    timeout=timeout,
                )
                return self.process_result(result, mode="propose")
            return {"skipped": True, "reason": "backlog_not_empty"}

        return {"skipped": True, "reason": "no_approved_features"}
