"""Google Docs integration for content review."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


@dataclass
class DocResult:
    success: bool
    doc_id: str | None = None
    url: str | None = None
    error: str | None = None


class GoogleDocsClient:
    """Create and populate Google Docs for content review."""

    def __init__(
        self,
        service: Any = None,
        drive_service: Any = None,
        folder_id: str = "",
        enabled: bool = False,
    ) -> None:
        self.service = service
        self.drive_service = drive_service
        self.folder_id = folder_id
        self.enabled = enabled

    @classmethod
    def from_config(cls, config: Any) -> GoogleDocsClient:
        """Build client from GoogleDocsConfig.  Returns disabled if no token."""
        if not config.enabled:
            return cls(enabled=False)

        token_path = Path(config.token_file).expanduser()
        if not token_path.exists():
            logger.warning("Google token not found at %s — Google Docs disabled", token_path)
            return cls(enabled=False)

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            if creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request

                creds.refresh(Request())
                token_path.write_text(creds.to_json())

            docs_service = build("docs", "v1", credentials=creds)
            drive_service = build("drive", "v3", credentials=creds)
            return cls(
                service=docs_service,
                drive_service=drive_service,
                folder_id=config.folder_id,
                enabled=True,
            )
        except Exception as e:
            logger.error("Failed to initialize Google Docs client: %s", e)
            return cls(enabled=False)

    @staticmethod
    def authorize(config: Any) -> bool:
        """Run one-time OAuth browser flow, save refresh token.

        Returns True on success.
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds_path = Path(config.credentials_file).expanduser()
        token_path = Path(config.token_file).expanduser()

        if not creds_path.exists():
            logger.error("Credentials file not found: %s", creds_path)
            return False

        token_path.parent.mkdir(parents=True, exist_ok=True)

        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
        logger.info("Google token saved to %s", token_path)
        return True

    def create_document(
        self,
        title: str,
        body: str,
        image_prompt: str | None = None,
    ) -> DocResult:
        """Create a Google Doc with markdown-ish content.

        Args:
            title: Document title.
            body: Markdown body text.
            image_prompt: Optional image generation prompt to append.

        Returns:
            DocResult with doc_id and url on success.
        """
        if not self.enabled:
            return DocResult(success=False, error="Google Docs disabled")

        try:
            doc = self.service.documents().create(body={"title": title}).execute()
            doc_id = doc["documentId"]

            # Build content to insert
            full_text = body.rstrip("\n")
            if image_prompt:
                full_text += "\n\n---\n\n## Image Generation Prompt\n\n" + image_prompt.strip()

            requests = _markdown_to_requests(full_text)
            if requests:
                self.service.documents().batchUpdate(
                    documentId=doc_id, body={"requests": requests}
                ).execute()

            # Move to folder if configured
            if self.folder_id:
                self.drive_service.files().update(
                    fileId=doc_id,
                    addParents=self.folder_id,
                    removeParents="root",
                    fields="id,parents",
                ).execute()

            url = f"https://docs.google.com/document/d/{doc_id}/edit"
            logger.info("Created Google Doc: %s", url)
            return DocResult(success=True, doc_id=doc_id, url=url)

        except Exception as e:
            logger.error("Failed to create Google Doc: %s", e)
            return DocResult(success=False, error=str(e))


def _markdown_to_requests(text: str) -> list[dict[str, Any]]:
    """Convert markdown text to Google Docs API batchUpdate requests.

    Handles: headings (#/##/###), **bold**, code blocks, bullet lists, [links](url).
    """
    requests: list[dict[str, Any]] = []
    # Track formatting ranges to apply after all text is inserted
    format_ops: list[dict[str, Any]] = []

    lines = text.split("\n")
    # We insert all text first, then apply formatting.
    # Google Docs API inserts at index 1 (after the implicit newline).
    # We build the full text and track ranges for formatting.

    segments: list[dict[str, Any]] = []  # {text, heading, bold_ranges, code, bullet, links}

    i = 0
    while i < len(lines):
        line = lines[i]

        # Code block
        if line.strip().startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            segments.append({"text": "\n".join(code_lines) + "\n", "code": True})
            continue

        # Heading
        heading_match = re.match(r"^(#{1,3})\s+(.*)", line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2)
            segments.append({"text": heading_text + "\n", "heading": level})
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$", line.strip()):
            segments.append({"text": "---\n", "code": False})
            i += 1
            continue

        # Bullet
        bullet_match = re.match(r"^[-*]\s+(.*)", line)
        if bullet_match:
            segments.append({"text": bullet_match.group(1) + "\n", "bullet": True})
            i += 1
            continue

        # Regular line
        segments.append({"text": line + "\n", "code": False})
        i += 1

    # Now build the full document text and collect formatting
    cursor = 1  # Docs start at index 1
    for seg in segments:
        raw = seg["text"]
        # Extract inline formatting before inserting
        # Process bold and links within the raw text
        clean_text, inline_formats = _parse_inline(raw, cursor)

        # Insert the clean text
        requests.append({
            "insertText": {
                "location": {"index": cursor},
                "text": clean_text,
            }
        })

        seg_len = len(clean_text)

        # Heading style
        if seg.get("heading"):
            level = seg["heading"]
            named = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3"}
            style = named.get(level, "HEADING_3")
            format_ops.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": cursor, "endIndex": cursor + seg_len},
                    "paragraphStyle": {"namedStyleType": style},
                    "fields": "namedStyleType",
                }
            })

        # Code block — monospace font
        if seg.get("code"):
            format_ops.append({
                "updateTextStyle": {
                    "range": {"startIndex": cursor, "endIndex": cursor + seg_len},
                    "textStyle": {
                        "weightedFontFamily": {"fontFamily": "Courier New"},
                    },
                    "fields": "weightedFontFamily",
                }
            })

        # Bullet
        if seg.get("bullet"):
            format_ops.append({
                "createParagraphBullets": {
                    "range": {"startIndex": cursor, "endIndex": cursor + seg_len},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })

        # Inline bold and link formatting
        format_ops.extend(inline_formats)

        cursor += seg_len

    # Append formatting ops after all inserts
    requests.extend(format_ops)
    return requests


def _parse_inline(
    text: str, base_offset: int
) -> tuple[str, list[dict[str, Any]]]:
    """Strip inline markdown (**bold**, [text](url)) and return clean text + format ops."""
    formats: list[dict[str, Any]] = []
    result = ""
    pos = 0

    while pos < len(text):
        # Bold: **text**
        bold_match = re.match(r"\*\*(.+?)\*\*", text[pos:])
        if bold_match:
            start = base_offset + len(result)
            inner = bold_match.group(1)
            result += inner
            end = base_offset + len(result)
            formats.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })
            pos += bold_match.end()
            continue

        # Link: [text](url)
        link_match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", text[pos:])
        if link_match:
            start = base_offset + len(result)
            link_text = link_match.group(1)
            link_url = link_match.group(2)
            result += link_text
            end = base_offset + len(result)
            formats.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"link": {"url": link_url}},
                    "fields": "link",
                }
            })
            pos += link_match.end()
            continue

        result += text[pos]
        pos += 1

    return result, formats
