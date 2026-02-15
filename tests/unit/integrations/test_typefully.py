"""Tests for Typefully REST client."""

from unittest.mock import MagicMock, patch

import pytest

from wiz.config.schema import SocialManagerConfig
from wiz.integrations.typefully import DraftResult, TypefullyClient


class TestTypefullyClient:
    def test_disabled_client_skips_create(self):
        client = TypefullyClient(api_key="", social_set_id=0, enabled=False)
        result = client.create_draft([{"text": "hello"}])
        assert result.success is True
        assert result.error == "disabled"

    def test_disabled_client_returns_empty_list(self):
        client = TypefullyClient(api_key="", social_set_id=0, enabled=False)
        assert client.list_drafts() == []

    @patch("wiz.integrations.typefully.os.environ", {"TYPEFULLY_API_KEY": "test-key"})
    def test_from_config_enabled(self):
        config = SocialManagerConfig(typefully_social_set_id=12345)
        client = TypefullyClient.from_config(config)
        assert client.enabled is True
        assert client.api_key == "test-key"
        assert client.social_set_id == 12345

    @patch("wiz.integrations.typefully.os.environ", {})
    def test_from_config_disabled_no_key(self):
        config = SocialManagerConfig(typefully_social_set_id=12345)
        client = TypefullyClient.from_config(config)
        assert client.enabled is False

    @patch("wiz.integrations.typefully.os.environ", {"TYPEFULLY_API_KEY": "key"})
    def test_from_config_disabled_no_social_set(self):
        config = SocialManagerConfig(typefully_social_set_id=0)
        client = TypefullyClient.from_config(config)
        assert client.enabled is False

    @patch("wiz.integrations.typefully.requests.post")
    def test_create_draft_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 42, "status": "draft"}
        mock_post.return_value = mock_resp

        client = TypefullyClient(api_key="key", social_set_id=100)
        result = client.create_draft(
            posts=[{"text": "Hello world"}],
            platforms=["x"],
            draft_title="Test Draft",
        )

        assert result.success is True
        assert result.draft_id == 42
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        body = call_kwargs[1]["json"]
        assert body["platforms"]["x"]["enabled"] is True
        assert body["platforms"]["x"]["posts"][0]["text"] == "Hello world"
        assert body["draft_title"] == "Test Draft"

    @patch("wiz.integrations.typefully.requests.post")
    def test_create_draft_multi_platform(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": 99}
        mock_post.return_value = mock_resp

        client = TypefullyClient(api_key="key", social_set_id=100)
        result = client.create_draft(
            posts=[{"text": "General text", "linkedin_text": "LinkedIn text"}],
            platforms=["x", "linkedin"],
        )

        assert result.success is True
        body = mock_post.call_args[1]["json"]
        assert body["platforms"]["x"]["posts"][0]["text"] == "General text"
        assert body["platforms"]["linkedin"]["posts"][0]["text"] == "LinkedIn text"

    @patch("wiz.integrations.typefully.requests.post")
    def test_create_draft_api_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"
        mock_post.return_value = mock_resp

        client = TypefullyClient(api_key="key", social_set_id=100)
        result = client.create_draft([{"text": "hello"}])
        assert result.success is False
        assert "400" in result.error

    @patch("wiz.integrations.typefully.requests.post")
    def test_create_draft_network_error(self, mock_post):
        import requests as req
        mock_post.side_effect = req.ConnectionError("timeout")

        client = TypefullyClient(api_key="key", social_set_id=100)
        result = client.create_draft([{"text": "hello"}])
        assert result.success is False
        assert "failed" in result.error.lower()

    @patch("wiz.integrations.typefully.requests.get")
    def test_list_drafts_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": [{"id": 1}, {"id": 2}]}
        mock_get.return_value = mock_resp

        client = TypefullyClient(api_key="key", social_set_id=100)
        drafts = client.list_drafts(status="draft", limit=5)
        assert len(drafts) == 2
        mock_get.assert_called_once()
        assert mock_get.call_args[1]["params"]["status"] == "draft"

    @patch("wiz.integrations.typefully.requests.get")
    def test_list_drafts_returns_list_directly(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": 1}]
        mock_get.return_value = mock_resp

        client = TypefullyClient(api_key="key", social_set_id=100)
        drafts = client.list_drafts()
        assert len(drafts) == 1

    @patch("wiz.integrations.typefully.requests.get")
    def test_list_drafts_api_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server error"
        mock_get.return_value = mock_resp

        client = TypefullyClient(api_key="key", social_set_id=100)
        assert client.list_drafts() == []

    def test_headers_include_api_key(self):
        client = TypefullyClient(api_key="my-key", social_set_id=100)
        headers = client._headers()
        assert headers["Authorization"] == "Bearer my-key"

    @patch("wiz.integrations.typefully.requests.post")
    def test_linkedin_merges_thread_into_single_post(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 55}
        mock_post.return_value = mock_resp

        client = TypefullyClient(api_key="key", social_set_id=100)
        client.create_draft(
            posts=[{"text": "Post 1"}, {"text": "Post 2"}, {"text": "Post 3"}],
            platforms=["x", "linkedin"],
        )

        body = mock_post.call_args[1]["json"]
        # X should get all 3 posts as a thread
        assert len(body["platforms"]["x"]["posts"]) == 3
        # LinkedIn should merge into 1 post
        assert len(body["platforms"]["linkedin"]["posts"]) == 1
        assert "Post 1" in body["platforms"]["linkedin"]["posts"][0]["text"]
        assert "Post 3" in body["platforms"]["linkedin"]["posts"][0]["text"]

    def test_no_publish_at_in_create(self):
        """Verify create_draft never sends publish_at — drafts only."""
        client = TypefullyClient(api_key="key", social_set_id=100, enabled=False)
        # Disabled client won't make a request, but we can verify the method signature
        # has no publish_at parameter
        import inspect
        sig = inspect.signature(client.create_draft)
        assert "publish_at" not in sig.parameters
