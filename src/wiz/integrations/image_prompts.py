"""Save image generation prompts to files, separate from published content."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_PROMPTS_DIR = "~/Documents/image-prompts"


def save_image_prompt(
    title: str,
    prompt_text: str,
    source: str = "social",
    output_dir: str = DEFAULT_IMAGE_PROMPTS_DIR,
) -> Path | None:
    """Save an image generation prompt to a markdown file.

    Args:
        title: Content title (used for filename).
        prompt_text: The image generation prompt.
        source: Where this came from ("social", "blog").
        output_dir: Directory to write files to.

    Returns:
        Path to the saved file, or None on failure.
    """
    try:
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = _slugify(title)
        filename = f"{date_str}-{slug}.md"
        path = out / filename

        content = f"""# Image Prompt: {title}

**Source:** {source}
**Date:** {date_str}

## Prompt

{prompt_text.strip()}
"""
        path.write_text(content)
        logger.info("Saved image prompt to %s", path)
        return path
    except Exception as e:
        logger.error("Failed to save image prompt: %s", e)
        return None


def extract_image_prompts(drafts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract image_prompt fields from parsed draft blocks.

    Returns list of dicts with 'title' and 'prompt' keys.
    """
    prompts: list[dict[str, str]] = []
    for draft in drafts:
        prompt = draft.get("image_prompt", "").strip()
        if prompt:
            title = draft.get("draft_title", "untitled")
            prompts.append({"title": title, "prompt": prompt})
    return prompts


def save_all_image_prompts(
    drafts: list[dict[str, Any]],
    source: str = "social",
    output_dir: str = DEFAULT_IMAGE_PROMPTS_DIR,
) -> list[Path]:
    """Extract and save all image prompts from parsed drafts.

    Returns list of paths to saved files.
    """
    extracted = extract_image_prompts(drafts)
    paths: list[Path] = []
    for item in extracted:
        path = save_image_prompt(
            title=item["title"],
            prompt_text=item["prompt"],
            source=source,
            output_dir=output_dir,
        )
        if path:
            paths.append(path)
    return paths


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:60].strip("-")
