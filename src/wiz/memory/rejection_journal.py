"""Persistent rejection journal for learning from review feedback."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RejectionJournal:
    """Records and retrieves rejection feedback in JSONL format.

    Storage: one JSONL file per repo under base_dir.
    """

    def __init__(self, base_dir: Path | str = "memory/rejections") -> None:
        self.base_dir = Path(base_dir)

    @staticmethod
    def _sanitize_repo(repo: str) -> str:
        """Sanitize a repo identifier for use as a filename.

        Replaces path separators and other unsafe characters with underscores
        to prevent path traversal and nested directory creation.
        """
        # Replace forward/back slashes with underscores (handles owner/repo slugs)
        safe = re.sub(r"[/\\]", "_", repo)
        # Remove path traversal components
        safe = safe.replace("..", "")
        # Strip any remaining characters that aren't alphanumeric, hyphen,
        # underscore, or dot
        safe = re.sub(r"[^\w.\-]", "_", safe)
        # Collapse multiple underscores
        safe = re.sub(r"_+", "_", safe)
        # Strip leading/trailing underscores and dots (avoid hidden files)
        safe = safe.strip("_.")
        # Fallback for empty result
        if not safe:
            safe = "unknown"
        return safe

    def _journal_path(self, repo: str) -> Path:
        """Build a safe journal file path for the given repo."""
        safe_name = self._sanitize_repo(repo)
        return self.base_dir / f"{safe_name}.jsonl"

    def record(
        self,
        repo: str,
        issue_number: int,
        branch: str,
        feedback: str,
        agent: str = "bug-fixer",
    ) -> None:
        """Append a rejection entry to the repo's journal file."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "repo": repo,
            "issue": issue_number,
            "branch": branch,
            "feedback": feedback,
            "agent": agent,
        }
        path = self._journal_path(repo)
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.debug("Recorded rejection for %s#%d", repo, issue_number)

    def read(
        self,
        repo: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read rejection entries with optional filters."""
        entries: list[dict[str, Any]] = []

        if repo:
            files = [self._journal_path(repo)]
        else:
            if not self.base_dir.exists():
                return []
            files = list(self.base_dir.glob("*.jsonl"))

        for path in files:
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since:
                    ts = entry.get("timestamp", "")
                    try:
                        entry_time = datetime.fromisoformat(ts)
                        if entry_time < since:
                            continue
                    except (ValueError, TypeError):
                        continue
                entries.append(entry)

        # Sort by timestamp descending (most recent first)
        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return entries[:limit]

    def summary(
        self,
        repo: str | None = None,
        since: datetime | None = None,
    ) -> str:
        """Formatted summary of rejections for use in agent prompts."""
        entries = self.read(repo=repo, since=since, limit=100)
        if not entries:
            return "No rejections recorded."

        lines = [f"## Rejection History ({len(entries)} entries)\n"]
        for entry in entries:
            ts = entry.get("timestamp", "unknown")
            r = entry.get("repo", "?")
            issue = entry.get("issue", "?")
            agent = entry.get("agent", "?")
            feedback = entry.get("feedback", "")
            # Truncate feedback for summary
            if len(feedback) > 200:
                feedback = feedback[:200] + "..."
            lines.append(f"- [{r}#{issue}] ({agent}, {ts}): {feedback}")

        return "\n".join(lines)
