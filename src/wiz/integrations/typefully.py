"""Typefully REST API client for creating social media drafts."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import requests

from wiz.config.schema import SocialManagerConfig

logger = logging.getLogger(__name__)

TYPEFULLY_BASE_URL = "https://api.typefully.com/v2"


@dataclass
class DraftResult:
    success: bool
    draft_id: int | None = None
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class TypefullyClient:
    """Create and list Typefully drafts via REST API.

    Drafts only — never passes publish_at. No auto-publish path exists.
    """

    def __init__(
        self,
        api_key: str,
        social_set_id: int,
        enabled: bool = True,
        base_url: str = TYPEFULLY_BASE_URL,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.social_set_id = social_set_id
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: SocialManagerConfig) -> TypefullyClient:
        """Create from SocialManagerConfig. Returns disabled if key or ID missing."""
        api_key = os.environ.get("TYPEFULLY_API_KEY", "")
        social_set_id = config.typefully_social_set_id
        if not api_key or social_set_id == 0:
            return cls(api_key="", social_set_id=0, enabled=False)
        return cls(api_key=api_key, social_set_id=social_set_id, enabled=True)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_draft(
        self,
        posts: list[dict[str, str]],
        platforms: list[str] | None = None,
        draft_title: str | None = None,
    ) -> DraftResult:
        """Create a Typefully draft. Never publishes — drafts only.

        Args:
            posts: List of dicts with 'text' key (and optional platform-specific text).
            platforms: List of platform names to enable (e.g. ["x", "linkedin"]).
            draft_title: Optional internal title for the draft.
        """
        if not self.enabled:
            logger.debug("Typefully disabled, skipping draft creation")
            return DraftResult(success=True, error="disabled")

        if platforms is None:
            platforms = ["x"]

        # Platforms that only support a single post (no threads)
        single_post_platforms = {"linkedin"}

        platform_configs: dict[str, Any] = {}
        for platform in platforms:
            key = platform.lower()
            platform_posts = []
            for post in posts:
                text = post.get(f"{key}_text") or post.get("text", "")
                platform_posts.append({"text": text})

            # LinkedIn etc. only support one post — merge thread into single post
            if key in single_post_platforms and len(platform_posts) > 1:
                merged = "\n\n".join(p["text"] for p in platform_posts)
                platform_posts = [{"text": merged}]

            platform_configs[key] = {"enabled": True, "posts": platform_posts}

        body: dict[str, Any] = {"platforms": platform_configs}
        if draft_title:
            body["draft_title"] = draft_title

        try:
            resp = requests.post(
                f"{self.base_url}/social-sets/{self.social_set_id}/drafts",
                headers=self._headers(),
                json=body,
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                draft_id = data.get("id") or data.get("draft_id")
                logger.info("Created Typefully draft %s", draft_id)
                return DraftResult(success=True, draft_id=draft_id, data=data)
            else:
                error = f"Typefully API error {resp.status_code}: {resp.text}"
                logger.error(error)
                return DraftResult(success=False, error=error)
        except requests.RequestException as e:
            error = f"Typefully request failed: {e}"
            logger.error(error)
            return DraftResult(success=False, error=error)

    def list_drafts(
        self, status: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """List drafts for this social set."""
        if not self.enabled:
            return []

        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status

        try:
            resp = requests.get(
                f"{self.base_url}/social-sets/{self.social_set_id}/drafts",
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("items", data) if isinstance(data, dict) else data
            else:
                logger.error("Typefully list error %s: %s", resp.status_code, resp.text)
                return []
        except requests.RequestException as e:
            logger.error("Typefully list request failed: %s", e)
            return []
