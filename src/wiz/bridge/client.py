"""REST client for Coding Agent Bridge.

Pattern adapted from harness-bench cab_bridge.py:155-227.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _retry(
    fn: Any,
    max_retries: int = 3,
    backoff: float = 1.0,
    retryable: tuple[type[Exception], ...] = (
        requests.ConnectionError,
        requests.Timeout,
    ),
) -> Any:
    """Retry a callable with exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except retryable as e:
            last_exc = e
            if attempt < max_retries - 1:
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "Retry %d/%d after %.1fs: %s",
                    attempt + 1, max_retries, wait, e,
                )
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


class BridgeClient:
    """REST client for the Coding Agent Bridge API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4003",
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def health_check(self) -> bool:
        """Check if the bridge server is running."""
        try:
            def _check() -> bool:
                resp = requests.get(
                    f"{self.base_url}/health", timeout=10,
                )
                return resp.status_code == 200
            return _retry(
                _check, max_retries=self.max_retries,
            )
        except Exception:
            return False

    def create_session(
        self,
        name: str,
        cwd: str,
        agent: str = "claude",
        model: str | None = None,
        flags: list[str] | None = None,
    ) -> str | None:
        """Create a new session. Returns session ID or None on failure."""
        payload: dict[str, Any] = {
            "name": name,
            "cwd": cwd,
            "agent": agent,
        }
        if model:
            payload["model"] = model
        if flags:
            payload["flags"] = flags

        try:
            def _create() -> str | None:
                resp = requests.post(
                    f"{self.base_url}/sessions",
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                if "session" in data:
                    return data["session"].get("id")
                return data.get("id")
            return _retry(
                _create, max_retries=self.max_retries,
            )
        except Exception as e:
            logger.error("Failed to create session: %s", e)
            return None

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session info by ID."""
        try:
            resp = requests.get(
                f"{self.base_url}/sessions/{session_id}",
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions."""
        try:
            resp = requests.get(f"{self.base_url}/sessions", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("sessions", [])
        except Exception:
            return []

    def send_prompt(self, session_id: str, prompt: str) -> bool:
        """Send a prompt to a session."""
        try:
            def _send() -> bool:
                resp = requests.post(
                    f"{self.base_url}/sessions/{session_id}/prompt",
                    json={"prompt": prompt},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return True
            return _retry(
                _send, max_retries=self.max_retries,
            )
        except Exception as e:
            logger.error("Failed to send prompt: %s", e)
            return False

    def cancel_session(self, session_id: str) -> bool:
        """Cancel a running session."""
        try:
            resp = requests.post(
                f"{self.base_url}/sessions/{session_id}/cancel",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error("Failed to cancel session: %s", e)
            return False

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        try:
            resp = requests.delete(
                f"{self.base_url}/sessions/{session_id}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Failed to delete session: %s", e)
            return False

    def cleanup_all_sessions(self) -> int:
        """Delete all sessions on the bridge. Returns count deleted.

        Called at startup to ensure a clean slate — any sessions from
        prior runs are stale (no backing tmux processes).
        """
        sessions = self.list_sessions()
        if not sessions:
            return 0

        deleted = 0
        for s in sessions:
            sid = s.get("id")
            if sid and self.delete_session(sid):
                deleted += 1

        logger.info(
            "Cleaned up %d/%d stale sessions", deleted, len(sessions),
        )
        return deleted
