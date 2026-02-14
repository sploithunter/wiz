"""Blog Writer agent: proposes topics and writes drafts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BlogWriterConfig
from wiz.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = Path(__file__).parent.parent.parent.parent / "agents" / "blog-writer" / "CLAUDE.md"


class BlogWriterAgent(BaseAgent):
    agent_type = "claude"
    agent_name = "blog-writer"

    def __init__(
        self,
        runner: SessionRunner,
        config: BlogWriterConfig,
        memory: LongTermMemory | None = None,
    ) -> None:
        super().__init__(runner, config)
        self.blog_config = config
        self.memory = memory

    def build_prompt(self, **kwargs: Any) -> str:
        mode = kwargs.get("mode", "propose")
        instructions = ""
        if CLAUDE_MD_PATH.exists():
            instructions = CLAUDE_MD_PATH.read_text()

        memory_context = ""
        if self.memory:
            recent = self.memory.retrieve(["blog", "writing", "topics"])
            if recent:
                memory_context = "\n\n## Recent Topics (avoid overlap):\n"
                memory_context += "\n".join(f"- {kw}: {content[:100]}" for kw, content in recent)

        output_dir = self.blog_config.output_dir

        if mode == "propose":
            return f"""{instructions}
{memory_context}

## Task: Propose Blog Topics
Analyze recent project activity and propose ONE blog topic.
Save it as a brief outline.
"""
        else:
            topic = kwargs.get("topic", "")
            return f"""{instructions}
{memory_context}

## Task: Write Blog Draft
Topic: {topic}

Write a complete blog draft. Save to: {output_dir}/
Use markdown format with frontmatter (title, date, tags).
"""

    def process_result(self, result: SessionResult, **kwargs: Any) -> dict[str, Any]:
        if not result.success:
            return {"success": False, "reason": result.reason}

        # Update memory to track what was written
        if self.memory and kwargs.get("topic"):
            self.memory.update_topic(
                "recent-blog", "recent-blog.md", f"Wrote about: {kwargs['topic']}"
            )

        return {"success": True, "mode": kwargs.get("mode"), "reason": result.reason}
