"""Base agent class with template method pattern."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult

logger = logging.getLogger(__name__)

# Resolved repo root based on this file's location (src/wiz/agents/base.py)
_FALLBACK_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class BaseAgent(ABC):
    """Abstract base class for all Wiz agents.

    Uses template method pattern:
    run() calls build_prompt() -> runner.run() -> process_result()
    """

    agent_type: str = "claude"  # Default agent type for bridge
    agent_name: str = "base"

    def __init__(self, runner: SessionRunner, config: Any = None) -> None:
        self.runner = runner
        self.config = config

    def _load_instructions(self, cwd: str | None = None) -> str:
        """Load agent CLAUDE.md instructions from the repo root.

        Resolves ``agents/<agent_name>/CLAUDE.md`` relative to *cwd* first
        (the actual worktree/repo the agent operates in).  Falls back to the
        repo root derived from this source file's location.

        Returns the file contents, or an empty string if not found.
        """
        candidates: list[Path] = []
        if cwd:
            candidates.append(Path(cwd) / "agents" / self.agent_name / "CLAUDE.md")
        candidates.append(_FALLBACK_REPO_ROOT / "agents" / self.agent_name / "CLAUDE.md")

        for path in candidates:
            if path.exists():
                return path.read_text()
        return ""

    @abstractmethod
    def build_prompt(self, **kwargs: Any) -> str:
        """Build the prompt to send to the agent. Subclasses must implement."""

    @abstractmethod
    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        """Process the session result. Subclasses must implement.

        Returns a dict with agent-specific results.
        """

    def run(self, cwd: str, timeout: float = 600, **kwargs: Any) -> dict[str, Any]:
        """Run the agent: build prompt -> execute -> process result."""
        prompt = self.build_prompt(cwd=cwd, **kwargs)
        logger.info("Running %s agent in %s", self.agent_name, cwd)

        flags = getattr(self.config, "flags", None) or None
        model = getattr(self.config, "model", None) or None
        result = self.runner.run(
            name=f"wiz-{self.agent_name}",
            cwd=cwd,
            prompt=prompt,
            agent=self.agent_type,
            model=model,
            timeout=timeout,
            flags=flags,
        )

        logger.info(
            "%s agent finished: success=%s reason=%s elapsed=%.1fs",
            self.agent_name,
            result.success,
            result.reason,
            result.elapsed,
        )

        return self.process_result(result, **kwargs)
