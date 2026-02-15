"""File lock manager for coordinating agent access."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class FileLockManager:
    """JSON-based file locks with TTL expiry.

    Locks are stored in .wiz/locks/ with path encoding (/ -> --).
    """

    def __init__(self, repo_path: Path, lock_dir: str = ".wiz/locks", ttl: int = 600) -> None:
        self.repo_path = Path(repo_path)
        self.lock_dir = self.repo_path / lock_dir
        self.ttl = ttl

    def _encode_path(self, file_path: str) -> str:
        """Encode a file path for use as a lock filename."""
        return file_path.replace("/", "--").replace("\\", "--")

    def _lock_path(self, file_path: str) -> Path:
        return self.lock_dir / f"{self._encode_path(file_path)}.lock"

    def _is_expired(self, lock_data: dict) -> bool:
        acquired_at = lock_data.get("acquired_at", 0)
        ttl = lock_data.get("ttl", self.ttl)
        return time.time() - acquired_at > ttl

    def acquire(self, file_path: str, owner: str) -> bool:
        """Acquire a lock on a file path. Returns True if acquired."""
        lock_file = self._lock_path(file_path)

        # Check existing lock
        if lock_file.exists():
            try:
                data = json.loads(lock_file.read_text())
                if not self._is_expired(data):
                    if data.get("owner") == owner:
                        return True  # Already own it
                    logger.debug("Lock held by %s on %s", data.get("owner"), file_path)
                    return False
            except (json.JSONDecodeError, KeyError):
                pass  # Corrupt lock file, overwrite

        self.lock_dir.mkdir(parents=True, exist_ok=True)
        lock_data = {
            "file_path": file_path,
            "owner": owner,
            "acquired_at": time.time(),
            "ttl": self.ttl,
        }
        lock_file.write_text(json.dumps(lock_data, indent=2))
        logger.debug("Lock acquired on %s by %s", file_path, owner)
        return True

    def release(self, file_path: str, owner: str) -> bool:
        """Release a lock. Only the owner can release."""
        lock_file = self._lock_path(file_path)
        if not lock_file.exists():
            return True

        try:
            data = json.loads(lock_file.read_text())
            if data.get("owner") != owner:
                return False
        except (json.JSONDecodeError, KeyError):
            pass

        lock_file.unlink()
        logger.debug("Lock released on %s by %s", file_path, owner)
        return True

    def check(self, file_path: str) -> dict | None:
        """Check if a file is locked. Returns lock data or None."""
        lock_file = self._lock_path(file_path)
        if not lock_file.exists():
            return None

        try:
            data = json.loads(lock_file.read_text())
            if self._is_expired(data):
                lock_file.unlink()
                return None
            return data
        except (json.JSONDecodeError, KeyError):
            return None

    def release_all(self, owner: str) -> int:
        """Release all locks owned by a given owner. Returns count released."""
        if not self.lock_dir.exists():
            return 0

        released = 0
        for lock_file in self.lock_dir.glob("*.lock"):
            try:
                data = json.loads(lock_file.read_text())
                if data.get("owner") == owner:
                    lock_file.unlink()
                    released += 1
            except (json.JSONDecodeError, KeyError):
                continue
        if released:
            logger.info("Released %d locks for owner %s", released, owner)
        return released
