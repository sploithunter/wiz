"""Tests for file lock manager."""

import json
import time
from pathlib import Path

from wiz.coordination.file_lock import FileLockManager


class TestFileLockManager:
    def test_acquire_and_release(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        assert locks.acquire("src/main.py", "agent-1") is True
        assert locks.release("src/main.py", "agent-1") is True

    def test_conflict_detection(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        assert locks.acquire("src/main.py", "agent-1") is True
        assert locks.acquire("src/main.py", "agent-2") is False

    def test_same_owner_reacquire(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        assert locks.acquire("src/main.py", "agent-1") is True
        assert locks.acquire("src/main.py", "agent-1") is True

    def test_wrong_owner_cannot_release(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        locks.acquire("src/main.py", "agent-1")
        assert locks.release("src/main.py", "agent-2") is False

    def test_ttl_expiry(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=1)
        locks.acquire("src/main.py", "agent-1")
        # Manually expire the lock
        lock_file = locks._lock_path("src/main.py")
        data = json.loads(lock_file.read_text())
        data["acquired_at"] = time.time() - 10
        lock_file.write_text(json.dumps(data))

        # Another agent should be able to acquire
        assert locks.acquire("src/main.py", "agent-2") is True

    def test_check_locked(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        locks.acquire("src/main.py", "agent-1")
        data = locks.check("src/main.py")
        assert data is not None
        assert data["owner"] == "agent-1"

    def test_check_unlocked(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        assert locks.check("src/main.py") is None

    def test_check_expired(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=1)
        locks.acquire("src/main.py", "agent-1")
        lock_file = locks._lock_path("src/main.py")
        data = json.loads(lock_file.read_text())
        data["acquired_at"] = time.time() - 10
        lock_file.write_text(json.dumps(data))
        assert locks.check("src/main.py") is None

    def test_path_encoding(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        encoded = locks._encode_path("src/wiz/config/schema.py")
        assert "/" not in encoded
        assert "--" in encoded

    def test_release_all(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        locks.acquire("file1.py", "agent-1")
        locks.acquire("file2.py", "agent-1")
        locks.acquire("file3.py", "agent-2")

        released = locks.release_all("agent-1")
        assert released == 2
        assert locks.check("file1.py") is None
        assert locks.check("file2.py") is None
        assert locks.check("file3.py") is not None

    def test_release_all_empty(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        assert locks.release_all("agent-1") == 0

    def test_release_nonexistent(self, tmp_path: Path):
        locks = FileLockManager(tmp_path, ttl=60)
        assert locks.release("nonexistent.py", "agent-1") is True
