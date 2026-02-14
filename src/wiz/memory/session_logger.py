"""Session logger: timestamped log files with retention."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path


class SessionLogger:
    """Writes timestamped session logs and handles cleanup."""

    def __init__(self, log_dir: Path, retention_days: int = 30) -> None:
        self.log_dir = Path(log_dir)
        self.retention_days = retention_days
        self._current_log: Path | None = None
        self._session_start: float | None = None

    def start_session(self, name: str = "") -> Path:
        """Start a new session log. Returns the log file path."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{name}" if name else ""
        self._current_log = self.log_dir / f"session_{timestamp}{suffix}.log"
        self._session_start = time.time()
        self.log(f"Session started: {name or 'unnamed'}")
        return self._current_log

    def log(self, message: str) -> None:
        """Append a timestamped line to the current session log."""
        if self._current_log is None:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        with open(self._current_log, "a") as f:
            f.write(line)

    def end_session(self, summary: str = "") -> float:
        """End the current session. Returns elapsed seconds."""
        elapsed = 0.0
        if self._session_start is not None:
            elapsed = time.time() - self._session_start
        if summary:
            self.log(f"Summary: {summary}")
        self.log(f"Session ended ({elapsed:.1f}s)")
        self._current_log = None
        self._session_start = None
        return elapsed

    def cleanup_old(self) -> int:
        """Remove session logs older than retention period. Returns count removed."""
        if not self.log_dir.exists():
            return 0
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        removed = 0
        for log_file in self.log_dir.glob("session_*.log"):
            if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff:
                log_file.unlink()
                removed += 1
        return removed
