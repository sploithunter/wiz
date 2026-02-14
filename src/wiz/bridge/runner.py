"""High-level session runner combining client + monitor.

Pattern adapted from harness-bench cab_bridge.py:228-325.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
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

        For Claude: uses bridge (REST + WebSocket hooks) for session management.
        For Codex: runs `codex exec` directly as a subprocess (codex has no
        hook system, so the bridge can't detect completion).
        """
        if agent == "codex":
            return self._run_codex_exec(name, cwd, prompt, model, timeout)
        return self._run_bridge_session(name, cwd, prompt, agent, model, timeout)

    def _run_codex_exec(
        self,
        name: str,
        cwd: str,
        prompt: str,
        model: str | None = None,
        timeout: float = 600,
    ) -> SessionResult:
        """Run codex in non-interactive exec mode.

        codex exec runs the prompt and exits when done, so we just
        wait for the subprocess to finish.
        """
        if not shutil.which("codex"):
            return SessionResult(success=False, reason="codex_not_installed")

        start_time = time.time()

        # Write prompt to a temp file to avoid shell escaping issues
        prompt_file = None
        try:
            prompt_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", prefix="wiz-codex-", delete=False,
            )
            prompt_file.write(prompt)
            prompt_file.close()

            cmd = ["codex", "exec", "--full-auto"]
            if model:
                cmd.extend(["--model", model])
            # Read prompt from stdin via file
            cmd.append("-")

            logger.info("Running codex exec: %s (cwd=%s)", name, cwd)

            # Build env without CLAUDECODE to avoid nested-session errors
            import os
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

            with open(prompt_file.name) as stdin_file:
                proc = subprocess.run(
                    cmd,
                    cwd=cwd,
                    stdin=stdin_file,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                )

            elapsed = time.time() - start_time
            success = proc.returncode == 0

            if success:
                logger.info("codex exec completed in %.1fs", elapsed)
            else:
                logger.warning(
                    "codex exec failed (rc=%d) in %.1fs: %s",
                    proc.returncode, elapsed, proc.stderr[:500],
                )

            return SessionResult(
                success=success,
                reason="completed" if success else f"exit_code_{proc.returncode}",
                elapsed=elapsed,
            )

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            logger.warning("codex exec TIMEOUT after %ds", timeout)
            return SessionResult(success=False, reason="timeout", elapsed=elapsed)

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error("codex exec error: %s", e)
            return SessionResult(success=False, reason=str(e), elapsed=elapsed)

        finally:
            if prompt_file:
                Path(prompt_file.name).unlink(missing_ok=True)

    def _run_bridge_session(
        self,
        name: str,
        cwd: str,
        prompt: str,
        agent: str = "claude",
        model: str | None = None,
        timeout: float = 0,
    ) -> SessionResult:
        """Run a session via the bridge (REST + WebSocket hooks).

        Waits for a stop event or session status change to detect completion.
        If timeout > 0, enforces a hard timeout; otherwise runs until done.
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

            # Wait for completion (no timeout by default - agents run until done)
            while True:
                if timeout > 0 and time.time() - start_time >= timeout:
                    break

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
                        logger.info("Session went offline (agent exited)")
                        break

                # Periodic progress log
                elapsed = time.time() - start_time
                if int(elapsed) % 60 == 0 and int(elapsed) > 0:
                    logger.info("Still waiting... (%.0fs elapsed)", elapsed)

            elapsed = time.time() - start_time
            timed_out = timeout > 0 and elapsed >= timeout and not self.monitor.stop_detected

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
