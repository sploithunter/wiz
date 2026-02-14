"""Tests for session logger."""

import os
import time
from pathlib import Path

from wiz.memory.session_logger import SessionLogger


class TestSessionLogger:
    def test_log_naming_format(self, tmp_path: Path):
        logger = SessionLogger(tmp_path / "sessions")
        log_path = logger.start_session("dev-cycle")
        assert log_path.name.startswith("session_")
        assert "dev-cycle" in log_path.name
        assert log_path.suffix == ".log"

    def test_append(self, tmp_path: Path):
        logger = SessionLogger(tmp_path / "sessions")
        logger.start_session("test")
        logger.log("Test message 1")
        logger.log("Test message 2")
        content = logger._current_log.read_text()
        assert "Test message 1" in content
        assert "Test message 2" in content
        # Verify timestamp format
        assert "[20" in content

    def test_end_session_returns_elapsed(self, tmp_path: Path):
        logger = SessionLogger(tmp_path / "sessions")
        logger.start_session("test")
        time.sleep(0.1)
        elapsed = logger.end_session("Done")
        assert elapsed >= 0.1
        assert logger._current_log is None

    def test_log_without_session_is_noop(self, tmp_path: Path):
        logger = SessionLogger(tmp_path / "sessions")
        logger.log("Should not crash")

    def test_cleanup_retention(self, tmp_path: Path):
        log_dir = tmp_path / "sessions"
        log_dir.mkdir()

        # Create an old log file
        old_log = log_dir / "session_20200101_000000.log"
        old_log.write_text("old")
        # Set mtime to the past
        old_time = time.time() - (60 * 86400)  # 60 days ago
        os.utime(old_log, (old_time, old_time))

        # Create a recent log
        new_log = log_dir / "session_20260101_000000.log"
        new_log.write_text("new")

        logger = SessionLogger(log_dir, retention_days=30)
        removed = logger.cleanup_old()
        assert removed == 1
        assert not old_log.exists()
        assert new_log.exists()

    def test_cleanup_empty_dir(self, tmp_path: Path):
        logger = SessionLogger(tmp_path / "nonexistent")
        assert logger.cleanup_old() == 0
