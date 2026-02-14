"""Social Manager agent: creates Typefully drafts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import SocialManagerConfig
from wiz.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = (
    Path(__file__).parent.parent.parent.parent / "agents" / "social-manager" / "CLAUDE.md"
)


class SocialManagerAgent(BaseAgent):
    agent_type = "claude"
    agent_name = "social-manager"

    def __init__(
        self,
        runner: SessionRunner,
        config: SocialManagerConfig,
        memory: LongTermMemory | None = None,
    ) -> None:
        super().__init__(runner, config)
        self.social_config = config
        self.memory = memory

    def build_prompt(self, **kwargs: Any) -> str:
        if self.social_config.social_posts_per_week == 0:
            return ""

        instructions = ""
        if CLAUDE_MD_PATH.exists():
            instructions = CLAUDE_MD_PATH.read_text()

        memory_context = ""
        if self.memory:
            recent = self.memory.retrieve(["social", "posts", "twitter"])
            if recent:
                memory_context = "\n\n## Recent Posts (avoid repetition):\n"
                memory_context += "\n".join(f"- {kw}" for kw, _ in recent)

        platforms = ", ".join(self.social_config.platforms)

        return f"""{instructions}
{memory_context}

## Task
Create social media drafts for: {platforms}
Use Typefully MCP tools (typefully_create_draft) to save drafts.
All drafts are saved for review - never auto-publish.
Create up to {self.social_config.social_posts_per_week} drafts.
"""

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        return {"success": result.success, "reason": result.reason}

    def run(self, cwd: str, timeout: float = 300, **kwargs: Any) -> dict[str, Any]:
        if self.social_config.social_posts_per_week == 0:
            return {"skipped": True, "reason": "disabled"}

        prompt = self.build_prompt(**kwargs)
        result = self.runner.run(
            name="wiz-social-manager",
            cwd=cwd,
            prompt=prompt,
            agent=self.agent_type,
            timeout=timeout,
        )

        if result.success and self.memory:
            self.memory.update_topic(
                "recent-social", "recent-social.md", "Posted social content"
            )

        return self.process_result(result)
