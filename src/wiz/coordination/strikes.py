"""Strike tracker for escalation policy."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StrikeTracker:
    """Track per-issue strikes and per-file failures for escalation."""

    def __init__(self, strike_file: Path) -> None:
        self.strike_file = Path(strike_file)
        self._data: dict[str, Any] = {"issues": {}, "files": {}}
        self._load()

    def _load(self) -> None:
        if self.strike_file.exists():
            try:
                self._data = json.loads(self.strike_file.read_text())
            except (json.JSONDecodeError, KeyError):
                self._data = {"issues": {}, "files": {}}

    def _save(self) -> None:
        self.strike_file.parent.mkdir(parents=True, exist_ok=True)
        self.strike_file.write_text(json.dumps(self._data, indent=2))

    def record_issue_strike(self, issue_number: int, reason: str) -> int:
        """Record a strike for an issue. Returns new strike count."""
        key = str(issue_number)
        if key not in self._data["issues"]:
            self._data["issues"][key] = {"count": 0, "history": []}
        self._data["issues"][key]["count"] += 1
        self._data["issues"][key]["history"].append(reason)
        self._save()
        return self._data["issues"][key]["count"]

    def get_issue_strikes(self, issue_number: int) -> int:
        """Get strike count for an issue."""
        key = str(issue_number)
        return self._data["issues"].get(key, {}).get("count", 0)

    def record_file_failure(self, file_path: str, issue_number: int) -> int:
        """Record a failure for a file (across issues). Returns new count."""
        if file_path not in self._data["files"]:
            self._data["files"][file_path] = {"count": 0, "issues": []}
        self._data["files"][file_path]["count"] += 1
        if issue_number not in self._data["files"][file_path]["issues"]:
            self._data["files"][file_path]["issues"].append(issue_number)
        self._save()
        return self._data["files"][file_path]["count"]

    def is_escalated(self, issue_number: int, max_strikes: int = 3) -> bool:
        """Check if an issue has reached the escalation threshold."""
        return self.get_issue_strikes(issue_number) >= max_strikes

    def get_flagged_files(self, max_strikes: int = 3) -> list[str]:
        """Get files that have exceeded the failure threshold."""
        return [
            fp
            for fp, data in self._data["files"].items()
            if data.get("count", 0) >= max_strikes
        ]
