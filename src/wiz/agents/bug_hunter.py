"""Bug Hunter agent: finds bugs and creates GitHub issues."""

from __future__ import annotations

import logging
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BugHunterConfig
from wiz.coordination.github_issues import GitHubIssues

logger = logging.getLogger(__name__)


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
        instructions = self._load_instructions(kwargs.get("cwd"))

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

        docs_section = ""
        if self.bug_config.audit_docs:
            docs_section = """

## Documentation Audit
Also check for documentation gaps. File these as **P4** issues with labels "wiz-bug" AND "docs":
gh issue create -R {repo} --title "[P4] Docs: {description}" --body "..." --label "wiz-bug,docs"

Look for:
- Missing or incomplete README
- Public modules/classes with no docstrings
- Config options that exist in schema.py but are not documented
- Outdated examples or instructions that no longer match the code
- New features with no corresponding documentation

Only flag significant gaps — not missing docstrings on private helpers.
These count toward the maximum issues limit above.
"""

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
{docs_section}"""

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
