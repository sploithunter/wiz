"""Blog Writer agent: proposes topics and writes drafts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BlogWriterConfig
from wiz.integrations.google_docs import GoogleDocsClient
from wiz.integrations.image_prompts import save_all_image_prompts
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
        google_docs: GoogleDocsClient | None = None,
    ) -> None:
        super().__init__(runner, config)
        self.blog_config = config
        self.memory = memory
        self.google_docs = google_docs

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

        # Extract and save image prompts from JSON blocks in output
        from wiz.agents.social_manager import _extract_json_blocks

        text_chunks: list[str] = []
        for event in result.events:
            data = event.get("data", {})
            message = data.get("message", "")
            if message:
                text_chunks.append(message)
            text = event.get("text", "")
            if text:
                text_chunks.append(text)
        full_text = "\n".join(text_chunks)

        blocks = _extract_json_blocks(full_text)

        # Create Google Doc if enabled
        doc_url = None
        if self.google_docs and self.google_docs.enabled and full_text.strip():
            title = kwargs.get("topic") or "Blog Draft"
            image_prompt = ""
            for block in blocks:
                ip = block.get("image_prompt", "").strip()
                if ip:
                    image_prompt = ip
                    break
            doc_result = self.google_docs.create_document(
                title=title,
                body=full_text,
                image_prompt=image_prompt or None,
            )
            if doc_result.success:
                doc_url = doc_result.url
                logger.info("Created blog Google Doc: %s", doc_url)

        # Fall back to disk-based image prompts when Google Docs is disabled
        image_prompt_paths: list[Path] = []
        if not (self.google_docs and self.google_docs.enabled):
            image_prompt_paths = save_all_image_prompts(blocks, source="blog")
            if image_prompt_paths:
                logger.info("Saved %d blog image prompts", len(image_prompt_paths))

        return {
            "success": True,
            "mode": kwargs.get("mode"),
            "reason": result.reason,
            "image_prompts_saved": len(image_prompt_paths),
            "doc_url": doc_url,
        }
