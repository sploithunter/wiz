"""High-level session runner combining client + monitor.

Pattern adapted from harness-bench cab_bridge.py:228-325.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from wiz.bridge.client import BridgeClient
from wiz.bridge.monitor import BridgeEventMonitor
from wiz.bridge.types import SessionResult

logger = logging.getLogger(__name__)


class SessionRunner:
    """Runs a complete agent session lifecycle: create -> prompt -> wait -> cleanup."""

    def __init__(
        self,
        client: BridgeClient,
        monitor: BridgeEventMonitor,
        init_wait: float = 5.0,
        poll_interval: float = 2.0,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        cleanup_on_start: bool = True,
    ) -> None:
        self.client = client
        self.monitor = monitor
        self.init_wait = init_wait
        self.poll_interval = poll_interval
        self.on_event = on_event
        self._cleaned_up = False
        self._cleanup_on_start = cleanup_on_start

    def cleanup_stale_sessions(self) -> int:
        """Delete all stale sessions from the bridge.

        Called automatically on first run() to ensure a clean slate.
        """
        if self._cleaned_up:
            return 0
        self._cleaned_up = True
        count = self.client.cleanup_all_sessions()
        if count > 0:
            logger.info("Startup cleanup: removed %d stale sessions", count)
        return count

    def run(
        self,
        name: str,
        cwd: str,
        prompt: str,
        agent: str = "claude",
        model: str | None = None,
        timeout: float = 600,
    ) -> SessionResult:
        """Run a complete session lifecycle.

        1. Check server health
        2. Start WebSocket monitor
        3. Create session via REST
        4. Wait for agent initialization
        5. Send prompt
        6. Wait for stop event OR poll status OR timeout
        7. Return results
        8. Delete session in finally block
        """
        # Check server health
        if not self.client.health_check():
            return SessionResult(success=False, reason="bridge_unavailable")

        # Cleanup stale sessions on first run
        if self._cleanup_on_start:
            self.cleanup_stale_sessions()

        # Start WebSocket monitor
        self.monitor.clear()
        if self.on_event:
            self.monitor.on_event = self.on_event
        self.monitor.start()

        session_id: str | None = None
        start_time = time.time()

        try:
            # Create session
            logger.info("Creating %s session: %s", agent, name)
            session_id = self.client.create_session(name, cwd, agent, model)
            if not session_id:
                return SessionResult(success=False, reason="failed_to_create_session")

            logger.info("Session created: %s", session_id)

            # Wait for agent to initialize
            time.sleep(self.init_wait)

            # Send prompt
            logger.info("Sending prompt...")
            if not self.client.send_prompt(session_id, prompt):
                return SessionResult(success=False, reason="failed_to_send_prompt")

            logger.info("Prompt sent, waiting for completion...")

            # Wait for completion or timeout
            while time.time() - start_time < timeout:
                # Check for stop event via WebSocket
                if self.monitor.wait_for_stop(timeout=self.poll_interval):
                    logger.info("Stop event received")
                    break

                # Poll session status as backup
                session = self.client.get_session(session_id)
                if session:
                    status = session.get("status")
                    if status == "idle":
                        logger.info("Session became idle")
                        break
                    elif status == "offline":
                        logger.warning("Session went offline")
                        break

            elapsed = time.time() - start_time
            timed_out = elapsed >= timeout and not self.monitor.stop_detected

            if timed_out:
                logger.warning("TIMEOUT after %ds", timeout)

            reason = "timeout" if timed_out else "completed"
            return SessionResult(
                success=not timed_out,
                reason=reason,
                elapsed=elapsed,
                events=self.monitor.events,
            )

        finally:
            self.monitor.stop()
            if session_id:
                self.client.delete_session(session_id)
