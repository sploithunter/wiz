"""Rejection learner agent: analyzes rejection patterns and proposes CLAUDE.md improvements."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import RejectionLearnerConfig
from wiz.coordination.github_issues import GitHubIssues
from wiz.memory.rejection_journal import RejectionJournal

logger = logging.getLogger(__name__)

# Agent CLAUDE.md files that the learner can propose updates to
AGENT_CLAUDE_MD_PATHS: dict[str, Path] = {
    "bug-fixer": Path(__file__).parent.parent.parent.parent / "agents" / "bug-fixer" / "CLAUDE.md",
    "feature-proposer": Path(__file__).parent.parent.parent.parent / "agents" / "feature-proposer" / "CLAUDE.md",
    "reviewer": Path(__file__).parent.parent.parent.parent / "agents" / "reviewer" / "CLAUDE.md",
}


class RejectionLearnerAgent(BaseAgent):
    agent_type = "codex"
    agent_name = "rejection-learner"

    def __init__(
        self,
        runner: SessionRunner,
        config: RejectionLearnerConfig,
        journal: RejectionJournal,
        github: GitHubIssues,
    ) -> None:
        super().__init__(runner, config)
        self.learner_config = config
        self.journal = journal
        self.github = github

    def build_prompt(self, **kwargs: Any) -> str:
        """Build analysis prompt with journal summary and current CLAUDE.md contents."""
        journal_summary = self.journal.summary()

        # Load current CLAUDE.md contents for target agents
        claude_md_sections: list[str] = []
        for agent_name in self.learner_config.target_agents:
            path = AGENT_CLAUDE_MD_PATHS.get(agent_name)
            if path and path.exists():
                content = path.read_text()
                claude_md_sections.append(
                    f"### agents/{agent_name}/CLAUDE.md\n```\n{content}\n```"
                )

        claude_md_text = "\n\n".join(claude_md_sections) if claude_md_sections else "No CLAUDE.md files found."

        return f"""You are a learning analyst for Wiz, an AI agent system. Your job is to analyze
rejection feedback from code reviews and identify recurring patterns that could be prevented
by updating agent instructions.

## Rejection History

{journal_summary}

## Current Agent Instructions

{claude_md_text}

## Task

1. Analyze the rejection history for recurring patterns (a pattern = similar feedback appearing in 2+ rejections)
2. For each pattern found, propose a specific addition to the relevant agent's CLAUDE.md file
3. Only propose additions that would prevent the class of mistake — not fixes for individual bugs
4. Do NOT propose changes that duplicate existing instructions

Output your analysis as JSON:

```json
{{
  "patterns": [
    {{
      "name": "short pattern name",
      "count": 3,
      "description": "what keeps going wrong",
      "examples": ["issue #12", "issue #34"]
    }}
  ],
  "proposed_additions": [
    {{
      "file": "agents/bug-fixer/CLAUDE.md",
      "section": "## Testing Requirements",
      "addition": "The new instruction text to add"
    }}
  ]
}}
```

If no recurring patterns are found (fewer than 2 similar rejections), output:
```json
{{"patterns": [], "proposed_additions": []}}
```
"""

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        """Parse learner output and create GitHub issue with proposals."""
        if not result.success:
            return {"success": False, "reason": result.reason}

        all_text = self._collect_text(result)
        parsed = self._parse_output(all_text)

        if not parsed or not parsed.get("proposed_additions"):
            return {
                "success": True,
                "patterns_found": len(parsed.get("patterns", [])) if parsed else 0,
                "proposals": 0,
            }

        # Create GitHub issue with proposals
        issue_url = self._create_improvement_issue(parsed)

        return {
            "success": True,
            "patterns_found": len(parsed.get("patterns", [])),
            "proposals": len(parsed.get("proposed_additions", [])),
            "issue_url": issue_url,
        }

    @staticmethod
    def _collect_text(result: SessionResult) -> str:
        """Collect all text from result."""
        chunks: list[str] = []
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
    def _parse_output(text: str) -> dict[str, Any] | None:
        """Extract JSON from the agent's output."""
        pattern = r"```json\s*(\{.*?\})\s*```"
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                obj = json.loads(match.group(1))
                if isinstance(obj, dict) and "patterns" in obj:
                    return obj
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def _create_improvement_issue(self, parsed: dict[str, Any]) -> str | None:
        """Create a GitHub issue with proposed CLAUDE.md improvements."""
        patterns = parsed.get("patterns", [])
        proposals = parsed.get("proposed_additions", [])

        body_lines = ["## Rejection Pattern Analysis\n"]
        body_lines.append("The rejection learner identified recurring patterns in review feedback.\n")

        if patterns:
            body_lines.append("### Patterns Found\n")
            for p in patterns:
                name = p.get("name", "unnamed")
                count = p.get("count", 0)
                desc = p.get("description", "")
                examples = p.get("examples", [])
                body_lines.append(f"**{name}** ({count} occurrences)")
                body_lines.append(f"{desc}")
                if examples:
                    body_lines.append(f"Examples: {', '.join(str(e) for e in examples)}")
                body_lines.append("")

        if proposals:
            body_lines.append("### Proposed CLAUDE.md Additions\n")
            for prop in proposals:
                file = prop.get("file", "unknown")
                section = prop.get("section", "")
                addition = prop.get("addition", "")
                body_lines.append(f"**File:** `{file}`")
                if section:
                    body_lines.append(f"**Section:** {section}")
                body_lines.append(f"```\n{addition}\n```\n")

        body = "\n".join(body_lines)

        try:
            url = self.github.create_issue(
                title="[Learner] Proposed CLAUDE.md improvements from rejection patterns",
                body=body,
                labels=["wiz-improvement"],
            )
            logger.info("Created improvement issue: %s", url)
            return url
        except Exception as e:
            logger.error("Failed to create improvement issue: %s", e)
            return None
