"""Tests for bridge REST client."""

from unittest.mock import MagicMock, patch

import requests

from wiz.bridge.client import BridgeClient


class TestBridgeClient:
    def setup_method(self):
        self.client = BridgeClient("http://localhost:4003")

    @patch("wiz.bridge.client.requests.get")
    def test_health_check_success(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        assert self.client.health_check() is True

    @patch("wiz.bridge.client.requests.get")
    def test_health_check_failure(self, mock_get):
        mock_get.side_effect = requests.ConnectionError()
        assert self.client.health_check() is False

    @patch("wiz.bridge.client.requests.post")
    def test_create_session_nested_format(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"session": {"id": "sess-123"}},
        )
        mock_post.return_value.raise_for_status = MagicMock()
        result = self.client.create_session("test", "/tmp", "claude")
        assert result == "sess-123"

    @patch("wiz.bridge.client.requests.post")
    def test_create_session_flat_format(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "sess-456"},
        )
        mock_post.return_value.raise_for_status = MagicMock()
        result = self.client.create_session("test", "/tmp")
        assert result == "sess-456"

    @patch("wiz.bridge.client.requests.post")
    def test_create_session_with_model(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "s1"},
        )
        mock_post.return_value.raise_for_status = MagicMock()
        self.client.create_session("test", "/tmp", model="opus")
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "opus"

    @patch("wiz.bridge.client.requests.post")
    def test_create_session_flags_converted_to_object(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "s1"},
        )
        mock_post.return_value.raise_for_status = MagicMock()
        self.client.create_session("test", "/tmp", flags=["--chrome", "--verbose"])
        payload = mock_post.call_args[1]["json"]
        assert payload["flags"] == {"chrome": True, "verbose": True}

    @patch("wiz.bridge.client.requests.post")
    def test_create_session_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError()
        assert self.client.create_session("test", "/tmp") is None

    @patch("wiz.bridge.client.requests.get")
    def test_get_session(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "s1", "status": "idle"},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = self.client.get_session("s1")
        assert result["status"] == "idle"

    @patch("wiz.bridge.client.requests.get")
    def test_get_session_not_found(self, mock_get):
        mock_get.side_effect = requests.HTTPError()
        assert self.client.get_session("bad") is None

    @patch("wiz.bridge.client.requests.get")
    def test_list_sessions_array(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"id": "s1"}, {"id": "s2"}],
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = self.client.list_sessions()
        assert len(result) == 2

    @patch("wiz.bridge.client.requests.get")
    def test_list_sessions_object(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"sessions": [{"id": "s1"}]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = self.client.list_sessions()
        assert len(result) == 1

    @patch("wiz.bridge.client.requests.post")
    def test_send_prompt(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        assert self.client.send_prompt("s1", "do stuff") is True
        payload = mock_post.call_args[1]["json"]
        assert payload["prompt"] == "do stuff"

    @patch("wiz.bridge.client.requests.post")
    def test_send_prompt_failure(self, mock_post):
        mock_post.side_effect = requests.ConnectionError()
        assert self.client.send_prompt("s1", "test") is False

    @patch("wiz.bridge.client.requests.post")
    def test_cancel_session(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        assert self.client.cancel_session("s1") is True

    @patch("wiz.bridge.client.requests.delete")
    def test_delete_session(self, mock_delete):
        mock_delete.return_value = MagicMock(status_code=200)
        mock_delete.return_value.raise_for_status = MagicMock()
        assert self.client.delete_session("s1") is True

    @patch("wiz.bridge.client.requests.delete")
    def test_delete_session_failure(self, mock_delete):
        mock_delete.side_effect = requests.ConnectionError()
        assert self.client.delete_session("bad") is False

    @patch("wiz.bridge.client.requests.get")
    def test_list_sessions_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError()
        assert self.client.list_sessions() == []

    @patch("wiz.bridge.client.requests.post")
    def test_create_session_http_500(self, mock_post):
        resp = MagicMock(status_code=500)
        resp.raise_for_status.side_effect = requests.HTTPError("500")
        mock_post.return_value = resp
        assert self.client.create_session("test", "/tmp") is None

    @patch("wiz.bridge.client.requests.delete")
    @patch("wiz.bridge.client.requests.get")
    def test_cleanup_all_sessions(self, mock_get, mock_delete):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
        )
        mock_get.return_value.raise_for_status = MagicMock()
        mock_delete.return_value = MagicMock(status_code=200)
        mock_delete.return_value.raise_for_status = MagicMock()

        count = self.client.cleanup_all_sessions()
        assert count == 3
        assert mock_delete.call_count == 3

    @patch("wiz.bridge.client.requests.get")
    def test_cleanup_all_sessions_empty(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [],
        )
        mock_get.return_value.raise_for_status = MagicMock()
        assert self.client.cleanup_all_sessions() == 0

    @patch("wiz.bridge.client.requests.delete")
    @patch("wiz.bridge.client.requests.get")
    def test_cleanup_partial_failure(self, mock_get, mock_delete):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"id": "s1"}, {"id": "s2"}],
        )
        mock_get.return_value.raise_for_status = MagicMock()
        # First delete succeeds, second fails
        ok_resp = MagicMock(status_code=200)
        ok_resp.raise_for_status = MagicMock()
        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = requests.HTTPError("500")
        mock_delete.side_effect = [ok_resp, fail_resp]

        count = self.client.cleanup_all_sessions()
        assert count == 1

    @patch("wiz.bridge.client.requests.delete")
    @patch("wiz.bridge.client.requests.get")
    def test_cleanup_excludes_own_sessions(self, mock_get, mock_delete):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
        )
        mock_get.return_value.raise_for_status = MagicMock()
        mock_delete.return_value = MagicMock(status_code=200)
        mock_delete.return_value.raise_for_status = MagicMock()

        count = self.client.cleanup_all_sessions(exclude={"s2"})
        assert count == 2
        # s2 should NOT have been deleted
        deleted_urls = [call.args[0] for call in mock_delete.call_args_list]
        assert not any("s2" in url for url in deleted_urls)
