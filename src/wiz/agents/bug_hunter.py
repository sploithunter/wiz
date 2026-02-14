"""Bug Hunter agent: finds bugs and creates GitHub issues."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BugHunterConfig
from wiz.coordination.github_issues import GitHubIssues

logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = Path(__file__).parent.parent.parent.parent / "agents" / "bug-hunter" / "CLAUDE.md"


class BugHunterAgent(BaseAgent):
    agent_type = "codex"
    agent_name = "bug-hunter"

    def __init__(
        self,
        runner: SessionRunner,
        config: BugHunterConfig,
        github: GitHubIssues,
    ) -> None:
        super().__init__(runner, config)
        self.github = github
        self.bug_config = config

    def build_prompt(self, **kwargs: Any) -> str:
        """Build bug hunting prompt with existing issues context."""
        # Load CLAUDE.md instructions
        instructions = ""
        if CLAUDE_MD_PATH.exists():
            instructions = CLAUDE_MD_PATH.read_text()

        # Get existing issues to avoid duplicates
        existing = kwargs.get("existing_issues", [])
        existing_titles = [i.get("title", "") for i in existing]
        existing_section = ""
        if existing_titles:
            existing_section = (
                "\n\n## Existing Issues (do NOT duplicate these):\n"
                + "\n".join(f"- {t}" for t in existing_titles)
            )

        max_issues = self.bug_config.max_issues_per_run
        min_severity = self.bug_config.min_severity

        return f"""{instructions}

## Configuration
- Maximum issues to create: {max_issues}
- Minimum severity to report: {min_severity}
- Require proof-of-concept: {self.bug_config.require_poc}
{existing_section}

## Task
Analyze this repository for bugs. For each bug found, create a GitHub issue using:
gh issue create -R {{repo}} --title "[P{{severity}}] {{description}}" --body "..." --label "wiz-bug"

Focus on real, impactful bugs. No style issues or nitpicks.
"""

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        """Check GitHub for newly created bug issues."""
        if not result.success:
            return {"bugs_found": 0, "success": False, "reason": result.reason}

        # Query for issues created by this run
        issues = self.github.list_issues(labels=["wiz-bug"])
        return {
            "bugs_found": len(issues),
            "issues": issues,
            "success": True,
            "reason": result.reason,
        }
