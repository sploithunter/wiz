"""Social Manager agent: creates Typefully drafts."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import SocialManagerConfig
from wiz.integrations.google_docs import GoogleDocsClient
from wiz.integrations.image_prompts import save_all_image_prompts
from wiz.integrations.typefully import DraftResult, TypefullyClient
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
        typefully: TypefullyClient | None = None,
        google_docs: GoogleDocsClient | None = None,
    ) -> None:
        super().__init__(runner, config)
        self.social_config = config
        self.memory = memory
        self.typefully = typefully or TypefullyClient.from_config(config)
        self.google_docs = google_docs

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
Output each draft as a JSON code block with this schema:

```json
{{
  "draft_title": "Short internal title",
  "posts": [
    {{"text": "The post text for all platforms"}},
    {{"text": "Optional second post in thread"}}
  ],
  "image_prompt": "Detailed prompt for image generation: style, subject, composition, mood, colors. 16:9 for X cards, 1:1 for LinkedIn."
}}
```

You may output multiple JSON blocks for multiple drafts.
All drafts are saved for review — never auto-publish.
Create up to {self.social_config.social_posts_per_week} drafts.
"""

    @staticmethod
    def _parse_posts_from_result(result: SessionResult) -> list[dict[str, Any]]:
        """Extract JSON draft blocks from session result events."""
        text_chunks: list[str] = []
        for event in result.events:
            data = event.get("data", {})
            # assistant_message events contain the response text
            message = data.get("message", "")
            if message:
                text_chunks.append(message)
            # Also check for text in the event directly
            text = event.get("text", "")
            if text:
                text_chunks.append(text)

        full_text = "\n".join(text_chunks)

        # Also try the result reason as fallback (some setups put output there)
        if not full_text.strip() and result.reason:
            full_text = result.reason

        return _extract_json_blocks(full_text)

    def _create_typefully_drafts(
        self, drafts: list[dict[str, Any]]
    ) -> list[DraftResult]:
        """Create Typefully drafts from parsed JSON blocks."""
        results: list[DraftResult] = []
        for draft in drafts:
            posts = draft.get("posts", [])
            if not posts:
                continue
            title = draft.get("draft_title")
            dr = self.typefully.create_draft(
                posts=posts,
                platforms=self.social_config.platforms,
                draft_title=title,
            )
            results.append(dr)
        return results

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

        # Parse Claude's JSON output and create Typefully drafts
        drafts_parsed = self._parse_posts_from_result(result)
        draft_results: list[DraftResult] = []
        if drafts_parsed and self.typefully.enabled:
            draft_results = self._create_typefully_drafts(drafts_parsed)
            created = sum(1 for dr in draft_results if dr.success)
            logger.info("Created %d/%d Typefully drafts", created, len(draft_results))

        # Create companion Google Docs per draft (posts + image prompt)
        doc_urls: list[str] = []
        if drafts_parsed and self.google_docs and self.google_docs.enabled:
            for draft in drafts_parsed:
                title = draft.get("draft_title", "Social Draft")
                posts = draft.get("posts", [])
                body = "\n\n".join(p.get("text", "") for p in posts)
                image_prompt = draft.get("image_prompt", "").strip() or None
                doc_result = self.google_docs.create_document(
                    title=title, body=body, image_prompt=image_prompt
                )
                if doc_result.success and doc_result.url:
                    doc_urls.append(doc_result.url)
            if doc_urls:
                logger.info("Created %d social Google Docs", len(doc_urls))

        # Fall back to disk-based image prompts when Google Docs is disabled
        image_prompt_paths: list[Path] = []
        if not (self.google_docs and self.google_docs.enabled):
            image_prompt_paths = save_all_image_prompts(drafts_parsed, source="social")
            if image_prompt_paths:
                logger.info("Saved %d image prompts", len(image_prompt_paths))

        if result.success and self.memory:
            self.memory.update_topic(
                "recent-social", "recent-social.md", "Posted social content"
            )

        return {
            "success": result.success,
            "reason": result.reason,
            "drafts_parsed": len(drafts_parsed),
            "drafts_created": sum(1 for dr in draft_results if dr.success),
            "image_prompts_saved": len(image_prompt_paths),
            "doc_urls": doc_urls,
        }


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    """Extract JSON objects from ```json code blocks in text."""
    blocks: list[dict[str, Any]] = []
    pattern = r"```json\s*\n(.*?)\n\s*```"
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            obj = json.loads(match.group(1))
            if isinstance(obj, dict):
                blocks.append(obj)
        except json.JSONDecodeError:
            logger.debug("Failed to parse JSON block: %s", match.group(1)[:100])
    return blocks
