"""Self-improvement guard: protects critical files from unguarded changes."""

from __future__ import annotations

import fnmatch
import logging
from typing import Any

logger = logging.getLogger(__name__)

PROTECTED_PATTERNS = [
    "config/wiz.yaml",
    "CLAUDE.md",
    "agents/*/CLAUDE.md",
    "src/wiz/orchestrator/escalation.py",
    "src/wiz/config/schema.py",
]


class SelfImprovementGuard:
    """Validates PRs on the wiz repo to flag changes to protected files."""

    def __init__(self, patterns: list[str] | None = None) -> None:
        self.patterns = patterns or PROTECTED_PATTERNS

    def is_protected(self, file_path: str) -> bool:
        """Check if a file matches any protected pattern."""
        for pattern in self.patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return True
        return False

    def validate_changes(self, changed_files: list[str]) -> dict[str, Any]:
        """Validate a list of changed files against protected patterns.

        Returns dict with protected files found and whether human review is needed.
        """
        protected_found = [f for f in changed_files if self.is_protected(f)]
        non_protected = [f for f in changed_files if not self.is_protected(f)]

        return {
            "protected_files": protected_found,
            "non_protected_files": non_protected,
            "needs_human_review": len(protected_found) > 0,
            "description": (
                f"Changes to protected files: {', '.join(protected_found)}"
                if protected_found
                else "No protected files changed"
            ),
        }
