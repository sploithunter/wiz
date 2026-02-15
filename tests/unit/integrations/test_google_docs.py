"""Tests for Google Docs integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from wiz.config.schema import GoogleDocsConfig
from wiz.integrations.google_docs import (
    DocResult,
    GoogleDocsClient,
    _markdown_to_requests,
    _parse_inline,
)


class TestGoogleDocsClient:
    def _make_client(self, enabled=True, folder_id=""):
        service = MagicMock()
        drive_service = MagicMock()
        return GoogleDocsClient(
            service=service,
            drive_service=drive_service,
            folder_id=folder_id,
            enabled=enabled,
        )

    def test_disabled_client_skips(self):
        client = self._make_client(enabled=False)
        result = client.create_document("Title", "Body")
        assert result.success is False
        assert result.error == "Google Docs disabled"

    def test_create_document_success(self):
        client = self._make_client()
        client.service.documents().create().execute.return_value = {
            "documentId": "doc123"
        }
        client.service.documents().batchUpdate().execute.return_value = {}

        result = client.create_document("Test Doc", "# Hello\n\nWorld")
        assert result.success is True
        assert result.doc_id == "doc123"
        assert result.url == "https://docs.google.com/document/d/doc123/edit"

    def test_create_document_with_image_prompt(self):
        client = self._make_client()
        client.service.documents().create().execute.return_value = {
            "documentId": "doc456"
        }
        client.service.documents().batchUpdate().execute.return_value = {}

        result = client.create_document(
            "Post", "Content here", image_prompt="A futuristic city"
        )
        assert result.success is True
        # Verify batchUpdate was called (content includes image prompt section)
        client.service.documents().batchUpdate.assert_called()

    def test_create_document_moves_to_folder(self):
        client = self._make_client(folder_id="folder789")
        client.service.documents().create().execute.return_value = {
            "documentId": "doc_move"
        }
        client.service.documents().batchUpdate().execute.return_value = {}
        client.drive_service.files().update().execute.return_value = {}

        result = client.create_document("Title", "Body")
        assert result.success is True
        client.drive_service.files().update.assert_called()

    def test_create_document_no_folder_skip_move(self):
        client = self._make_client(folder_id="")
        client.service.documents().create().execute.return_value = {
            "documentId": "doc_nofolder"
        }
        client.service.documents().batchUpdate().execute.return_value = {}

        result = client.create_document("Title", "Body")
        assert result.success is True
        client.drive_service.files().update.assert_not_called()

    def test_create_document_handles_api_error(self):
        client = self._make_client()
        client.service.documents().create().execute.side_effect = Exception("API down")

        result = client.create_document("Title", "Body")
        assert result.success is False
        assert "API down" in result.error

    def test_from_config_disabled(self):
        config = GoogleDocsConfig(enabled=False)
        client = GoogleDocsClient.from_config(config)
        assert client.enabled is False

    def test_from_config_no_token_file(self, tmp_path):
        config = GoogleDocsConfig(
            enabled=True,
            token_file=str(tmp_path / "nonexistent.json"),
        )
        client = GoogleDocsClient.from_config(config)
        assert client.enabled is False


class TestAuthorize:
    @patch("wiz.integrations.google_docs.InstalledAppFlow", create=True)
    def test_authorize_missing_creds_file(self, _mock_flow, tmp_path):
        config = GoogleDocsConfig(
            enabled=True,
            credentials_file=str(tmp_path / "missing-creds.json"),
            token_file=str(tmp_path / "token.json"),
        )
        result = GoogleDocsClient.authorize(config)
        assert result is False

    @patch("google_auth_oauthlib.flow.InstalledAppFlow")
    def test_authorize_success(self, mock_flow_cls, tmp_path):
        creds_file = tmp_path / "creds.json"
        creds_file.write_text('{"installed":{}}')
        token_file = tmp_path / "token.json"

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "abc"}'
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        config = GoogleDocsConfig(
            enabled=True,
            credentials_file=str(creds_file),
            token_file=str(token_file),
        )
        result = GoogleDocsClient.authorize(config)
        assert result is True
        assert token_file.exists()


class TestMarkdownToRequests:
    def test_empty_text(self):
        reqs = _markdown_to_requests("")
        # Should produce at least the insert for the empty line
        assert isinstance(reqs, list)

    def test_heading(self):
        reqs = _markdown_to_requests("# Title")
        # Should have insertText and updateParagraphStyle
        insert_ops = [r for r in reqs if "insertText" in r]
        heading_ops = [r for r in reqs if "updateParagraphStyle" in r]
        assert len(insert_ops) >= 1
        assert len(heading_ops) >= 1
        assert heading_ops[0]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"

    def test_h2_heading(self):
        reqs = _markdown_to_requests("## Subtitle")
        heading_ops = [r for r in reqs if "updateParagraphStyle" in r]
        assert heading_ops[0]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_2"

    def test_bold(self):
        reqs = _markdown_to_requests("This is **bold** text")
        bold_ops = [r for r in reqs if "updateTextStyle" in r and r["updateTextStyle"].get("textStyle", {}).get("bold")]
        assert len(bold_ops) >= 1

    def test_code_block(self):
        text = "```python\nprint('hello')\n```"
        reqs = _markdown_to_requests(text)
        mono_ops = [r for r in reqs if "updateTextStyle" in r and "weightedFontFamily" in r.get("updateTextStyle", {}).get("textStyle", {})]
        assert len(mono_ops) >= 1

    def test_bullet_list(self):
        reqs = _markdown_to_requests("- item one\n- item two")
        bullet_ops = [r for r in reqs if "createParagraphBullets" in r]
        assert len(bullet_ops) == 2

    def test_link(self):
        reqs = _markdown_to_requests("[Click here](https://example.com)")
        link_ops = [r for r in reqs if "updateTextStyle" in r and "link" in r.get("updateTextStyle", {}).get("textStyle", {})]
        assert len(link_ops) >= 1


class TestParseInline:
    def test_plain_text(self):
        clean, fmts = _parse_inline("hello world", 0)
        assert clean == "hello world"
        assert fmts == []

    def test_bold_stripped(self):
        clean, fmts = _parse_inline("say **hello** now", 0)
        assert clean == "say hello now"
        assert len(fmts) == 1
        assert fmts[0]["updateTextStyle"]["textStyle"]["bold"] is True

    def test_link_stripped(self):
        clean, fmts = _parse_inline("[click](https://x.com)", 0)
        assert clean == "click"
        assert len(fmts) == 1
        assert fmts[0]["updateTextStyle"]["textStyle"]["link"]["url"] == "https://x.com"

    def test_offset_applied(self):
        clean, fmts = _parse_inline("**hi**", 10)
        assert fmts[0]["updateTextStyle"]["range"]["startIndex"] == 10
        assert fmts[0]["updateTextStyle"]["range"]["endIndex"] == 12
