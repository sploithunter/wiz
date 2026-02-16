"""High-level session runner combining client + monitor.

Pattern adapted from harness-bench cab_bridge.py:228-325.
"""

from __future__ import annotations

import json
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

# Hook script that bridges Claude Code events to the bridge's event pipeline
_HOOK_SCRIPT = str(Path.home() / ".cin-interface" / "hooks" / "coding-agent-hook.sh")

# Required hook event types for bridge event correlation
_REQUIRED_HOOKS = ("Stop", "PreToolUse", "PostToolUse", "Notification", "SubagentStop")

_HOOK_ENTRY = {
    "matcher": "*",
    "hooks": [{"type": "command", "command": _HOOK_SCRIPT, "timeout": 5}],
}


def ensure_hooks(cwd: str | None = None) -> bool:
    """Ensure Claude Code hooks are configured for the target CWD.

    Writes hooks to a project-level .claude/settings.local.json in the
    target CWD. This file takes precedence over ~/.claude/settings.json
    and won't be clobbered by other Claude Code sessions modifying the
    global settings.
    """
    if not Path(_HOOK_SCRIPT).exists():
        logger.warning("Hook script not found: %s", _HOOK_SCRIPT)
        return False

    targets: list[Path] = []

    # Always ensure global settings have hooks
    targets.append(Path.home() / ".claude" / "settings.json")

    # Also write to project-level settings if CWD provided
    if cwd:
        targets.append(Path(cwd) / ".claude" / "settings.local.json")

    try:
        for settings_path in targets:
            if settings_path.exists():
                data = json.loads(settings_path.read_text())
            else:
                data = {}

            hooks = data.get("hooks", {})
            changed = False

            for event_type in _REQUIRED_HOOKS:
                if event_type not in hooks:
                    hooks[event_type] = [_HOOK_ENTRY]
                    changed = True
                else:
                    # Check if our hook script is already in the list
                    # Scan ALL commands in every hooks array, not just [0]
                    existing_cmds = [
                        cmd.get("command", "")
                        for h in hooks[event_type]
                        for cmd in h.get("hooks", [])
                    ]
                    if _HOOK_SCRIPT not in existing_cmds:
                        hooks[event_type].append(_HOOK_ENTRY)
                        changed = True

            if changed:
                data["hooks"] = hooks
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_text(json.dumps(data, indent=2) + "\n")
                logger.info("Installed hooks in %s", settings_path)
            else:
                logger.debug("Hooks already configured in %s", settings_path)

        return True

    except Exception as e:
        logger.error("Failed to ensure hooks: %s", e)
        return False


class SessionRunner:
    """Runs a complete agent session lifecycle: create -> prompt -> wait -> cleanup."""

    # Track session IDs created by THIS process so we never clean them up
    _own_session_ids: set[str] = set()

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

    def run(
        self,
        name: str,
        cwd: str,
        prompt: str,
        agent: str = "claude",
        model: str | None = None,
        timeout: float = 600,
        flags: list[str] | None = None,
    ) -> SessionResult:
        """Run a complete session lifecycle.

        For Claude: uses bridge (REST + WebSocket hooks) for session management.
        For Codex: runs `codex exec` directly as a subprocess (codex has no
        hook system, so the bridge can't detect completion).
        """
        if agent == "codex":
            return self._run_codex_exec(name, cwd, prompt, model, timeout)
        return self._run_bridge_session(name, cwd, prompt, agent, model, timeout, flags)

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
                output=proc.stdout or "",
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
        flags: list[str] | None = None,
    ) -> SessionResult:
        """Run a session via the bridge (REST + WebSocket hooks).

        Waits for a stop event or session status change to detect completion.
        If timeout > 0, enforces a hard timeout; otherwise runs until done.
        """
        # Check server health
        if not self.client.health_check():
            return SessionResult(success=False, reason="bridge_unavailable")

        # Ensure hooks are installed before launching Claude Code
        ensure_hooks(cwd)

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
            session_id = self.client.create_session(name, cwd, agent, model, flags)
            if not session_id:
                return SessionResult(success=False, reason="failed_to_create_session")

            SessionRunner._own_session_ids.add(session_id)
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
                SessionRunner._own_session_ids.discard(session_id)
                self.client.delete_session(session_id)
