"""Blog Writer agent: proposes topics and writes drafts."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from wiz.agents.base import BaseAgent
from wiz.bridge.runner import SessionRunner
from wiz.bridge.types import SessionResult
from wiz.config.schema import BlogWriterConfig, RepoConfig
from wiz.integrations.google_docs import GoogleDocsClient
from wiz.integrations.image_prompts import save_all_image_prompts
from wiz.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = Path(__file__).parent.parent.parent.parent / "agents" / "blog-writer" / "CLAUDE.md"

# Memory keywords for topic lifecycle
PROPOSED_TOPIC_KEY = "blog-proposed-topic"
PROPOSED_TOPIC_FILE = "blog-proposed-topic.md"

# Limits
MAX_SESSION_LOG_FILES = 5
MAX_LOG_LINES_PER_FILE = 20


def gather_session_log_context(session_log_dir: Path, max_files: int = MAX_SESSION_LOG_FILES) -> str:
    """Read recent session logs and extract summaries."""
    if not session_log_dir.exists():
        return ""

    log_files = sorted(session_log_dir.glob("session_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not log_files:
        return ""

    lines: list[str] = []
    for log_file in log_files[:max_files]:
        try:
            content = log_file.read_text()
            file_lines = content.strip().splitlines()
            # Take last N lines (most relevant — session end + summary)
            tail = file_lines[-MAX_LOG_LINES_PER_FILE:] if len(file_lines) > MAX_LOG_LINES_PER_FILE else file_lines
            lines.append(f"### {log_file.name}")
            lines.extend(tail)
            lines.append("")
        except OSError:
            continue

    return "\n".join(lines) if lines else ""


def gather_github_activity(
    repos: list[RepoConfig],
    exclude_repos: list[str],
    limit: int = 10,
) -> str:
    """Fetch recent GitHub issues and comments from configured repos."""
    exclude_patterns = [r.lower() for r in exclude_repos]
    lines: list[str] = []

    for repo in repos:
        if not repo.enabled:
            continue
        repo_name = repo.github.lower()
        short_name = repo.name.lower()
        if any(pat in repo_name or pat in short_name for pat in exclude_patterns):
            continue

        # Fetch recent issues (open + recently closed)
        try:
            result = subprocess.run(
                ["gh", "issue", "list", "-R", repo.github,
                 "--state", "all", "--limit", str(limit),
                 "--json", "number,title,state,updatedAt,labels"],
                capture_output=True, text=True, check=True, timeout=15,
            )
            issues = json.loads(result.stdout) if result.stdout.strip() else []
            if issues:
                lines.append(f"### {repo.github} — Recent Issues")
                for issue in issues[:limit]:
                    state = issue.get("state", "")
                    title = issue.get("title", "")
                    num = issue.get("number", "")
                    label_names = [l.get("name", "") for l in issue.get("labels", [])]
                    label_str = f" [{', '.join(label_names)}]" if label_names else ""
                    lines.append(f"- #{num} ({state}) {title}{label_str}")
                lines.append("")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            logger.debug("Could not fetch issues for %s", repo.github)

        # Fetch recent issue comments
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{repo.github}/issues/comments",
                 "--jq", ".[:5] | .[] | {body: .body[:200], issue_url: .issue_url, updated_at: .updated_at}",
                 "-q", ".[:5]"],
                capture_output=True, text=True, check=True, timeout=15,
            )
            if result.stdout.strip():
                # gh api with --jq returns newline-separated JSON objects
                comments_text = result.stdout.strip()
                if comments_text:
                    lines.append(f"### {repo.github} — Recent Comments")
                    lines.append(comments_text[:1000])  # cap total size
                    lines.append("")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            logger.debug("Could not fetch comments for %s", repo.github)

    return "\n".join(lines) if lines else ""


class BlogWriterAgent(BaseAgent):
    agent_type = "claude"
    agent_name = "blog-writer"

    def __init__(
        self,
        runner: SessionRunner,
        config: BlogWriterConfig,
        memory: LongTermMemory | None = None,
        google_docs: GoogleDocsClient | None = None,
        repos: list[RepoConfig] | None = None,
    ) -> None:
        super().__init__(runner, config)
        self.blog_config = config
        self.memory = memory
        self.google_docs = google_docs
        self.repos = repos or []

    def _get_pending_topic(self) -> str | None:
        """Check memory for a previously proposed topic awaiting writing."""
        if not self.memory:
            return None
        results = self.memory.retrieve([PROPOSED_TOPIC_KEY])
        for kw, content in results:
            if kw == PROPOSED_TOPIC_KEY and content.strip():
                return content.strip()
        return None

    def _store_proposed_topic(self, result: SessionResult) -> str | None:
        """Extract topic from propose-mode output and store in memory."""
        if not self.memory:
            return None

        # Collect all text from events
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

        if not full_text.strip():
            full_text = result.reason or ""

        if full_text.strip():
            self.memory.update_topic(
                PROPOSED_TOPIC_KEY, PROPOSED_TOPIC_FILE, full_text.strip()
            )
            self.memory.save_index()
            logger.info("Stored proposed blog topic in memory")
            return full_text.strip()
        return None

    def _consume_pending_topic(self) -> None:
        """Remove the pending topic from memory after writing."""
        if self.memory:
            self.memory.delete_topic(PROPOSED_TOPIC_KEY)
            self.memory.save_index()

    def _gather_activity_context(self) -> str:
        """Gather project activity context from configured sources."""
        ctx = self.blog_config.context_sources
        sections: list[str] = []

        if ctx.session_logs:
            # Session logs are in memory/sessions/ relative to project root
            session_dir = Path("memory/sessions")
            log_text = gather_session_log_context(session_dir)
            if log_text:
                sections.append("## Recent Wiz Session Activity\n" + log_text)

        if ctx.github_activity and self.repos:
            gh_text = gather_github_activity(
                self.repos,
                exclude_repos=ctx.exclude_repos,
                limit=ctx.github_activity_limit,
            )
            if gh_text:
                sections.append("## Recent GitHub Activity\n" + gh_text)

        return "\n\n".join(sections)

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

        activity_context = self._gather_activity_context()
        output_dir = self.blog_config.output_dir

        if mode == "propose":
            return f"""{instructions}
{memory_context}
{activity_context}

## Task: Propose Blog Topics
Analyze the recent project activity above and propose ONE blog topic.
The topic should be grounded in real work — what was built, fixed, or learned.
Save it as a brief outline.
"""
        else:
            topic = kwargs.get("topic", "")
            return f"""{instructions}
{memory_context}
{activity_context}

## Task: Write Blog Draft
Topic: {topic}

Write a complete blog draft. Save to: {output_dir}/
Use markdown format with frontmatter (title, date, tags).
Draw on the project activity context above where relevant.
"""

    def run(self, cwd: str, timeout: float = 600, **kwargs: Any) -> dict[str, Any]:
        """Run blog writer with automatic mode transition.

        Logic:
        1. If a pending topic exists in memory → write mode (consume topic)
        2. Else if auto_propose_topics → propose mode (store topic for next run)
        3. Otherwise → skip
        """
        pending_topic = self._get_pending_topic()

        if pending_topic:
            if self.blog_config.require_approval:
                logger.info(
                    "Pending topic awaiting approval (require_approval=True)"
                )
                return {
                    "skipped": True,
                    "reason": "awaiting_approval",
                    "pending_topic": pending_topic,
                }

            # Write mode: draft the pending topic
            logger.info("Found pending topic, switching to write mode")
            prompt = self.build_prompt(mode="write", topic=pending_topic)
            result = self.runner.run(
                name="wiz-blog-write",
                cwd=cwd,
                prompt=prompt,
                agent=self.agent_type,
                timeout=timeout,
                flags=self.blog_config.flags or None,
            )

            if result.success:
                self._consume_pending_topic()

            return self.process_result(result, mode="write", topic=pending_topic)

        elif self.blog_config.auto_propose_topics:
            # Propose mode: generate a topic for next run
            logger.info("No pending topic, running in propose mode")
            prompt = self.build_prompt(mode="propose")
            result = self.runner.run(
                name="wiz-blog-propose",
                cwd=cwd,
                prompt=prompt,
                agent=self.agent_type,
                timeout=timeout,
                flags=self.blog_config.flags or None,
            )

            if result.success:
                self._store_proposed_topic(result)

            return self.process_result(result, mode="propose")

        return {"skipped": True, "reason": "no_pending_topics"}

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
